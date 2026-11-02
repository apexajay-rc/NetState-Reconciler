from __future__ import annotations

from pathlib import Path

from netstate_reconciler.engine import NetStateEngine, StateStore
from netstate_reconciler.intent import load_intent
from netstate_reconciler.reconcile import compare_acl_attachments, parse_ios_config


INTENT = """
routers:
  R1:
    acls:
      - name: GUEST_TO_FINANCE
        interface: GigabitEthernet0/1.20
        direction: in
        rules:
          - action: deny
            protocol: ip
            source: 10.10.20.0/24
            destination: 10.10.30.0/24
          - action: permit
            protocol: ip
            source: any
            destination: any
"""

CONFIG_ATTACHED = """hostname R1
ip access-list extended GUEST_TO_FINANCE
 deny ip 10.10.20.0 0.0.0.255 10.10.30.0 0.0.0.255
 permit ip any any
!
interface GigabitEthernet0/1.20
 encapsulation dot1Q 20
 ip address 10.10.20.1 255.255.255.0
 ip access-group GUEST_TO_FINANCE in
!
end
"""

CONFIG_DETACHED = CONFIG_ATTACHED.replace(" ip access-group GUEST_TO_FINANCE in\n", "")


def _ok(text: str = "OK"):
    return {"isError": False, "structured": {"result": text}, "content": [{"type": "text", "text": text}], "text": text, "raw": {"isError": False, "content": [{"type": "text", "text": text}]}}


class FakeToolbox:
    def __init__(self):
        self.configs = {"R1": CONFIG_ATTACHED}

    def has(self, *names):
        available = {"pt_cli", "pt_backup_config"}
        return next((name for name in names if name in available), None)

    def invoke(self, name, semantic=None):
        return _ok('{"checkpoint":"saved"}')

    def cli(self, device, commands):
        if commands == ["show running-config"]:
            return [_ok(self.configs[device])]
        config = self.configs[device]
        current_interface = None
        for command in commands:
            if command.startswith("interface "):
                current_interface = command.split(None, 1)[1]
            elif command.startswith("no ip access-group ") and current_interface:
                acl_name, direction = command.split()[-2:]
                config = config.replace(f" ip access-group {acl_name} {direction}\n", "")
            elif command.startswith("ip access-group ") and current_interface:
                acl_name, direction = command.split()[-2:]
                if f" ip access-group {acl_name} {direction}\n" not in config:
                    marker = f"interface {current_interface}\n"
                    config = config.replace(marker, marker + f" ip access-group {acl_name} {direction}\n")
        self.configs[device] = config
        return [_ok("CLI commands completed")]


def test_parser_finds_acl_definition_and_interface_attachment():
    facts = parse_ios_config(CONFIG_ATTACHED)
    assert "guest_to_finance" in facts.acl_definitions
    item = facts.interfaces["gigabitethernet0/1.20"]
    assert item["acl_attachments"]["in"] == "GUEST_TO_FINANCE"


def test_compare_reports_missing_acl_attachment_as_actionable_drift():
    intent = load_intent(INTENT)
    findings = compare_acl_attachments(intent, {"R1": CONFIG_DETACHED})
    assert len(findings) == 1
    assert findings[0].code == "MISSING_ACL_ATTACHMENT"
    assert findings[0].auto_remediable is True
    assert "ip access-group GUEST_TO_FINANCE in" in findings[0].remediation_commands


def test_compare_reports_compliance_when_acl_is_attached():
    intent = load_intent(INTENT)
    assert compare_acl_attachments(intent, {"R1": CONFIG_ATTACHED}) == []


def test_missing_acl_definition_is_not_auto_remediated():
    intent = load_intent(INTENT)
    no_acl = CONFIG_DETACHED.replace("ip access-list extended GUEST_TO_FINANCE\n deny ip 10.10.20.0 0.0.0.255 10.10.30.0 0.0.0.255\n permit ip any any\n", "")
    findings = compare_acl_attachments(intent, {"R1": no_acl})
    assert findings[0].code == "ACL_DEFINITION_MISSING"
    assert findings[0].auto_remediable is False


def test_simulate_then_reconcile_acl_attachment_end_to_end(tmp_path: Path):
    intent = load_intent(INTENT)
    toolbox = FakeToolbox()
    engine = NetStateEngine(toolbox, StateStore(tmp_path / ".netstate"))

    simulated = engine.simulate_acl_attachment_drift(
        intent, "R1", "GUEST_TO_FINANCE", approved=True
    )
    assert simulated["status"] == "DRIFT_INJECTED"
    assert engine.analyze_intent_drift(intent)["findings"][0]["code"] == "MISSING_ACL_ATTACHMENT"

    repaired = engine.remediate_acl_drift(intent, approved=True)
    assert repaired["status"] == "VERIFIED"
    assert repaired["after_findings"] == []
    assert engine.analyze_intent_drift(intent)["findings"] == []


def test_simulation_requires_explicit_approval(tmp_path: Path):
    intent = load_intent(INTENT)
    engine = NetStateEngine(FakeToolbox(), StateStore(tmp_path / ".netstate"))
    try:
        engine.simulate_acl_attachment_drift(intent, "R1", "GUEST_TO_FINANCE", approved=False)
    except Exception as exc:
        assert "approval" in str(exc).lower()
    else:
        raise AssertionError("Simulation must require explicit approval")


def test_remediation_does_not_overwrite_missing_acl_definition(tmp_path: Path):
    intent = load_intent(INTENT)
    toolbox = FakeToolbox()
    toolbox.configs["R1"] = CONFIG_DETACHED.replace(
        "ip access-list extended GUEST_TO_FINANCE\n deny ip 10.10.20.0 0.0.0.255 10.10.30.0 0.0.0.255\n permit ip any any\n", ""
    )
    engine = NetStateEngine(toolbox, StateStore(tmp_path / ".netstate"))
    result = engine.remediate_acl_drift(intent, approved=True, allow_without_checkpoint=True)
    assert result["status"] == "BLOCKED"
    assert result["unsupported_findings"][0]["code"] == "ACL_DEFINITION_MISSING"


def test_wrong_acl_attachment_is_detected_and_targets_expected_acl_only():
    intent = load_intent(INTENT)
    wrong = CONFIG_ATTACHED.replace("ip access-group GUEST_TO_FINANCE in", "ip access-group TEMP_ACL in")
    findings = compare_acl_attachments(intent, {"R1": wrong})
    assert len(findings) == 1
    assert findings[0].code == "WRONG_ACL_ATTACHMENT"
    assert findings[0].auto_remediable is True
    assert findings[0].remediation_commands == [
        "configure terminal", "interface GigabitEthernet0/1.20",
        "ip access-group GUEST_TO_FINANCE in", "exit", "end", "write memory",
    ]


def test_simulation_refuses_to_detach_an_acl_that_is_not_currently_attached(tmp_path: Path):
    intent = load_intent(INTENT)
    toolbox = FakeToolbox()
    toolbox.configs["R1"] = CONFIG_DETACHED
    engine = NetStateEngine(toolbox, StateStore(tmp_path / ".netstate"))
    try:
        engine.simulate_acl_attachment_drift(intent, "R1", "GUEST_TO_FINANCE", approved=True)
    except Exception as exc:
        assert "but observed no ACL" in str(exc)
    else:
        raise AssertionError("Fault injection must refuse unexpected pre-existing state")


def test_store_persists_desired_intent_without_secret_fields(tmp_path: Path):
    intent = load_intent(INTENT)
    store = StateStore(tmp_path / ".netstate")
    store.save_desired_intent(intent)
    loaded = store.load_desired_intent()
    assert loaded is not None
    assert loaded.model_dump(mode="json") == intent.model_dump(mode="json")

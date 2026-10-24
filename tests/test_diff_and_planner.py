from pathlib import Path

from netstate.configuration import load_desired
from netstate.parsers.ios import CiscoIOSParser
from netstate.reconciler.diff import compare_states
from netstate.remediation.planner import build_plan

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


def load_actual(filename="router1_running.txt"):
    parser = CiscoIOSParser()
    return parser.parse((FIXTURES / filename).read_text())


def test_baseline_is_compliant():
    desired = load_desired(ROOT / "configs/router1.yaml")
    actual = load_actual()
    assert compare_states(desired, actual) == []


def test_drift_detects_ip_and_acl_changes():
    desired = load_desired(ROOT / "configs/router1.yaml")
    actual = load_actual("router1_with_drift.txt")
    drifts = compare_states(desired, actual)
    paths = {item.path for item in drifts}
    assert "interfaces.GigabitEthernet0/0.ipv4_address" in paths
    assert "acls.100.entries" in paths
    assert any(item.severity == "CRITICAL" for item in drifts)


def test_acl_plan_requires_manual_review():
    desired = load_desired(ROOT / "configs/router1.yaml")
    actual = load_actual("router1_with_drift.txt")
    drifts = compare_states(desired, actual)
    actions = build_plan(desired, actual, drifts)
    acl_action = next(action for action in actions if action.path == "acls.100")
    assert not acl_action.auto_applicable
    assert acl_action.requires_approval
    assert acl_action.commands


def test_non_strict_mode_ignores_undeclared_resources():
    desired = {"hostname": "Router1", "strict": False}
    actual = {"hostname": "Router1", "interfaces": {"GigabitEthernet0/0": {}}, "acls": {"5": {}}}
    assert compare_states(desired, actual) == []


def test_strict_mode_flags_undeclared_resources():
    desired = {"hostname": "Router1", "interfaces": {}, "strict": True}
    actual = {"hostname": "Router1", "interfaces": {"GigabitEthernet0/0": {}}}
    drifts = compare_states(desired, actual)
    assert any(item.path == "interfaces.GigabitEthernet0/0" for item in drifts)


def test_planner_does_not_remove_undeclared_outbound_acl_binding():
    desired = {
        "interfaces": {"GigabitEthernet0/0": {"description": "Changed", "access_groups": {"in": "100"}}}
    }
    actual = {
        "interfaces": {
            "GigabitEthernet0/0": {
                "description": "Old", "access_groups": {"in": "100", "out": "200"}, "admin_state": "up"
            }
        }
    }
    drifts = compare_states(desired, actual)
    actions = build_plan(desired, actual, drifts)
    commands = [command for action in actions for command in action.commands]
    assert "no ip access-group 200 out" not in commands
    assert "description Changed" in commands

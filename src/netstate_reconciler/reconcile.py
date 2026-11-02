from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .binding import normalize_interface_name
from .models import NetworkIntent


@dataclass(frozen=True)
class ACLAttachment:
    interface: str
    acl_name: str
    direction: str


@dataclass
class DriftFinding:
    device: str
    code: str
    severity: str
    object_name: str
    expected: str
    observed: str
    explanation: str
    auto_remediable: bool = False
    remediation_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConfigFacts:
    interfaces: dict[str, dict[str, Any]] = field(default_factory=dict)
    acl_definitions: set[str] = field(default_factory=set)
    acl_attachments: list[ACLAttachment] = field(default_factory=list)


def _strip_prompt(line: str) -> str:
    value = line.strip()
    # MCP CLI output may echo a device prompt before the command/config line.
    match = re.match(r"^[A-Za-z0-9_.-]+(?:\([^)]*\))?[>#]\s*(.*)$", value)
    return match.group(1).strip() if match else value


def parse_ios_config(text: str) -> ConfigFacts:
    """Parse the bounded IOS configuration subset used by drift reconciliation.

    This parser intentionally extracts facts only; it is not a complete IOS grammar.
    Unknown syntax is ignored rather than guessed.
    """
    facts = ConfigFacts()
    current_interface: str | None = None
    current_acl: str | None = None
    for raw_line in text.splitlines():
        line = _strip_prompt(raw_line)
        if not line or line == "!" or line.startswith("<credential"):
            continue
        interface_match = re.match(r"^interface\s+(\S+)", line, re.I)
        if interface_match:
            current_interface = interface_match.group(1)
            facts.interfaces.setdefault(normalize_interface_name(current_interface), {
                "name": current_interface, "acl_attachments": {},
            })
            current_acl = None
            continue
        acl_match = re.match(r"^ip access-list (?:extended|standard)\s+(\S+)", line, re.I)
        if acl_match:
            current_acl = acl_match.group(1)
            facts.acl_definitions.add(current_acl.casefold())
            current_interface = None
            continue
        if re.match(r"^(?:router|line|vlan|ip dhcp pool|ip nat pool)\b", line, re.I):
            current_interface = None
            if not line.lower().startswith("ip access-list"):
                current_acl = None
            continue
        if current_interface:
            attach = re.match(r"^ip access-group\s+(\S+)\s+(in|out)\s*$", line, re.I)
            if attach:
                acl_name, direction = attach.groups()
                key = normalize_interface_name(current_interface)
                facts.interfaces[key]["acl_attachments"][direction.lower()] = acl_name
                facts.acl_attachments.append(ACLAttachment(current_interface, acl_name, direction.lower()))
        # Numbered ACLs are also accepted as definitions, though remediation of
        # named intent ACLs is the first supported automatic use case.
        numbered = re.match(r"^access-list\s+(\d+)\b", line, re.I)
        if numbered:
            facts.acl_definitions.add(numbered.group(1).casefold())
    return facts


def expected_acl_attachments(intent: NetworkIntent) -> dict[str, list[ACLAttachment]]:
    expected: dict[str, list[ACLAttachment]] = {}
    for device, router in intent.routers.items():
        for acl in router.acls:
            expected.setdefault(device, []).append(
                ACLAttachment(acl.interface, acl.name, acl.direction)
            )
    return expected


def compare_acl_attachments(
    intent: NetworkIntent,
    configs: dict[str, str],
) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    expected_by_device = expected_acl_attachments(intent)
    for device, expected_items in expected_by_device.items():
        if device not in configs:
            findings.append(DriftFinding(
                device=device,
                code="CONFIG_UNOBSERVED",
                severity="unknown",
                object_name="running-config",
                expected="Readable running configuration",
                observed="Not captured",
                explanation="NetState could not collect this device's running configuration. No compliance conclusion is possible.",
            ))
            continue
        facts = parse_ios_config(configs[device])
        for expected in expected_items:
            interface_key = normalize_interface_name(expected.interface)
            interface_facts = facts.interfaces.get(interface_key)
            if interface_facts is None:
                findings.append(DriftFinding(
                    device=device,
                    code="INTERFACE_NOT_OBSERVED",
                    severity="high",
                    object_name=expected.interface,
                    expected=f"Interface exists with ACL {expected.acl_name} ({expected.direction})",
                    observed="Interface section not present in running-config",
                    explanation="The configured interface was not found in the captured running configuration. Automatic repair is disabled because the interface state is uncertain.",
                ))
                continue
            observed_acl = interface_facts["acl_attachments"].get(expected.direction)
            if observed_acl and observed_acl.casefold() == expected.acl_name.casefold():
                continue
            if expected.acl_name.casefold() not in facts.acl_definitions:
                observed = observed_acl or "No ACL attached"
                findings.append(DriftFinding(
                    device=device,
                    code="ACL_DEFINITION_MISSING",
                    severity="high",
                    object_name=f"{expected.interface} / {expected.direction}",
                    expected=f"Defined ACL {expected.acl_name} attached {expected.direction}",
                    observed=f"{observed}; ACL definition not found",
                    explanation="The desired ACL definition is absent. NetState will not invent ACL rules or overwrite policy automatically.",
                ))
                continue
            code = "MISSING_ACL_ATTACHMENT" if not observed_acl else "WRONG_ACL_ATTACHMENT"
            expected_text = f"{expected.acl_name} ({expected.direction})"
            observed_text = f"No {expected.direction} ACL" if not observed_acl else f"{observed_acl} ({expected.direction})"
            commands = [
                "configure terminal",
                f"interface {expected.interface}",
                f"ip access-group {expected.acl_name} {expected.direction}",
                "exit",
                "end",
                "write memory",
            ]
            findings.append(DriftFinding(
                device=device,
                code=code,
                severity="high",
                object_name=expected.interface,
                expected=expected_text,
                observed=observed_text,
                explanation=(
                    "The intended access-control policy is not attached to this interface. "
                    "Attaching the existing ACL restores the declared policy."
                ),
                auto_remediable=True,
                remediation_commands=commands,
            ))
    return findings


def acl_drift_simulation_command(intent: NetworkIntent, device: str, acl_name: str) -> tuple[str, str, str]:
    """Return (interface, direction, command) for one ACL declared in the intent."""
    matches = []
    router = intent.routers.get(device)
    if router:
        matches = [acl for acl in router.acls if acl.name.casefold() == acl_name.casefold()]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one intent ACL named {acl_name!r} on {device}; found {len(matches)}.")
    acl = matches[0]
    return acl.interface, acl.direction, f"no ip access-group {acl.name} {acl.direction}"

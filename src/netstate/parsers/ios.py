"""Parser for a useful, explicitly bounded subset of Cisco IOS running-config syntax."""

from __future__ import annotations

import re
from typing import Any

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)\s*$", re.IGNORECASE)
_INTERFACE_RE = re.compile(r"^interface\s+(.+?)\s*$", re.IGNORECASE)
_IPV4_RE = re.compile(r"^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s*$", re.IGNORECASE)
_ACCESS_GROUP_RE = re.compile(r"^ip\s+access-group\s+(\S+)\s+(in|out)\s*$", re.IGNORECASE)
_ACL_NUMERIC_RE = re.compile(r"^access-list\s+(\S+)\s+(.+?)\s*$", re.IGNORECASE)
_ACL_HEADER_RE = re.compile(r"^ip\s+access-list\s+(standard|extended)\s+(\S+)\s*$", re.IGNORECASE)
_OSPF_RE = re.compile(r"^router\s+ospf\s+(\S+)", re.IGNORECASE)
_NETWORK_RE = re.compile(r"^network\s+(\S+)\s+(\S+)\s+area\s+(\S+)\s*$", re.IGNORECASE)
_ROUTER_ID_RE = re.compile(r"^router-id\s+(\S+)\s*$", re.IGNORECASE)


def _clean_acl_entry(entry: str) -> str:
    """Normalize whitespace and remove an optional leading sequence number."""
    tokens = entry.strip().split()
    if tokens and tokens[0].isdigit() and len(tokens) > 1:
        tokens = tokens[1:]
    return " ".join(tokens)


def _infer_acl_type(entry: str) -> str:
    tokens = _clean_acl_entry(entry).lower().split()
    if len(tokens) > 1 and tokens[0] in {"permit", "deny"}:
        return "standard" if tokens[1] == "host" or tokens[1] == "any" or tokens[1].count(".") == 3 else "extended"
    return "extended"


class CiscoIOSParser:
    """Convert IOS running-config text into the state model used by NetState.

    Parsed fields: hostname; interface IPv4 address/mask, admin state, description and
    inbound/outbound ACL bindings; numbered and named ACL entries; OSPF router-id/network
    statements. Other IOS features are intentionally outside this parser's current scope.
    """

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def parse(self, text: str) -> dict[str, Any]:
        self.warnings = []
        state: dict[str, Any] = {"interfaces": {}, "acls": {}, "ospf": {}}
        context: tuple[str, str] | None = None
        current_acl_type: str | None = None

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped in {"!", "end"}:
                if stripped == "!":
                    context = None
                    current_acl_type = None
                continue

            # Top-level commands are normally unindented. A leading indentation indicates
            # a subcommand, except that some exported files may indent everything uniformly.
            host_match = _HOSTNAME_RE.match(stripped)
            if host_match and not raw_line[:1].isspace():
                state["hostname"] = host_match.group(1)
                context = None
                current_acl_type = None
                continue

            interface_match = _INTERFACE_RE.match(stripped) if not raw_line[:1].isspace() else None
            if interface_match:
                name = interface_match.group(1).strip()
                state["interfaces"].setdefault(name, {"admin_state": "up", "access_groups": {}})
                context = ("interface", name)
                current_acl_type = None
                continue

            acl_header = _ACL_HEADER_RE.match(stripped) if not raw_line[:1].isspace() else None
            if acl_header:
                acl_type, name = acl_header.groups()
                state["acls"].setdefault(name, {"type": acl_type.lower(), "entries": []})
                context = ("named_acl", name)
                current_acl_type = acl_type.lower()
                continue

            numeric_acl = _ACL_NUMERIC_RE.match(stripped) if not raw_line[:1].isspace() else None
            if numeric_acl:
                name, entry = numeric_acl.groups()
                acl_name = str(name)
                acl = state["acls"].setdefault(acl_name, {"type": _infer_acl_type(entry), "entries": []})
                acl["entries"].append(_clean_acl_entry(entry))
                context = None
                current_acl_type = None
                continue

            ospf_match = _OSPF_RE.match(stripped) if not raw_line[:1].isspace() else None
            if ospf_match:
                process_id = ospf_match.group(1)
                state["ospf"].setdefault(process_id, {"networks": []})
                context = ("ospf", process_id)
                current_acl_type = None
                continue

            if context is None:
                continue

            kind, key = context
            if kind == "interface":
                interface = state["interfaces"][key]
                ipv4_match = _IPV4_RE.match(stripped)
                access_match = _ACCESS_GROUP_RE.match(stripped)
                if re.match(r"^ip\s+address\s+\S+\s+\S+\s+secondary\b", stripped, re.IGNORECASE):
                    self.warnings.append(f"Line {line_number}: Secondary IPv4 addresses are not modeled.")
                elif ipv4_match:
                    interface["ipv4_address"], interface["ipv4_mask"] = ipv4_match.groups()
                elif re.match(r"^ip\s+address\s+dhcp\b", stripped, re.IGNORECASE):
                    self.warnings.append(f"Line {line_number}: DHCP interface addressing is not modeled.")
                elif access_match:
                    acl_name, direction = access_match.groups()
                    interface["access_groups"][direction.lower()] = str(acl_name)
                elif stripped.lower() == "shutdown":
                    interface["admin_state"] = "down"
                elif stripped.lower() == "no shutdown":
                    interface["admin_state"] = "up"
                elif stripped.lower().startswith("description "):
                    interface["description"] = stripped[len("description "):]
                elif any(stripped.lower().startswith(prefix) for prefix in (
                    "ipv6 address ", "ip nat ", "ip helper-address ", "vrf forwarding ",
                    "switchport ", "standby ", "channel-group ", "encapsulation ",
                    "service-policy ", "ip ospf ", "ip policy ", "crypto map ",
                )):
                    self.warnings.append(
                        f"Line {line_number}: Interface command is outside the modeled subset: {stripped}"
                    )
                elif stripped.lower() in {"no ip address", "no description"}:
                    if stripped.lower() == "no ip address":
                        interface.pop("ipv4_address", None)
                        interface.pop("ipv4_mask", None)
                    else:
                        interface.pop("description", None)
            elif kind == "named_acl":
                entry = _clean_acl_entry(stripped)
                if entry:
                    state["acls"][key]["entries"].append(entry)
            elif kind == "ospf":
                network_match = _NETWORK_RE.match(stripped)
                router_id_match = _ROUTER_ID_RE.match(stripped)
                if network_match:
                    network, wildcard, area = network_match.groups()
                    state["ospf"][key]["networks"].append(
                        {"network": network, "wildcard": wildcard, "area": area}
                    )
                elif router_id_match:
                    state["ospf"][key]["router_id"] = router_id_match.group(1)
                elif any(stripped.lower().startswith(prefix) for prefix in (
                    "passive-interface", "redistribute ", "default-information ", "area ",
                    "authentication", "summary-address ", "timers ", "maximum-paths ",
                )):
                    self.warnings.append(
                        f"Line {line_number}: OSPF command is outside the modeled subset: {stripped}"
                    )

        # Empty sections add noise to reports, so omit sections never declared in the input.
        for section in ("interfaces", "acls", "ospf"):
            if not state[section]:
                del state[section]
        return state

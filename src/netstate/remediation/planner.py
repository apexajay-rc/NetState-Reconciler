"""Generate proposed CLI remediation actions from drift findings."""

from __future__ import annotations

from typing import Any

from netstate.models import Drift, RemediationAction


def _quote_cli(value: Any) -> str:
    text = str(value)
    if not text or any(char in text for char in "\r\n\x00"):
        raise ValueError("Unsafe line break or empty value in CLI command input.")
    return text


def build_plan(desired: dict[str, Any], actual: dict[str, Any], drifts: list[Drift]) -> list[RemediationAction]:
    """Produce reviewable actions. Only low-risk, well-scoped changes are auto-applicable.

    ACL and OSPF changes are proposed for manual review because command ordering and routing
    consequences depend on device context. Interface address/admin-state changes require approval.
    """
    actions: list[RemediationAction] = []
    seen_interfaces: set[str] = set()
    seen_acls: set[str] = set()
    seen_ospf: set[str] = set()

    for drift in drifts:
        parts = drift.path.split(".")
        if drift.path == "hostname":
            expected = desired.get("hostname")
            if expected:
                actions.append(RemediationAction(
                    path="hostname", summary=f"Set hostname to {expected}",
                    commands=[f"hostname {_quote_cli(expected)}"], severity=drift.severity,
                    auto_applicable=True, requires_approval=True,
                ))
            continue

        if len(parts) >= 2 and parts[0] == "interfaces":
            name = parts[1]
            if name in seen_interfaces:
                continue
            seen_interfaces.add(name)
            spec = desired.get("interfaces", {}).get(name)
            current = actual.get("interfaces", {}).get(name)
            if not isinstance(spec, dict) or not isinstance(current, dict):
                actions.append(RemediationAction(
                    path=f"interfaces.{name}", summary=f"Review interface {name} resource drift",
                    severity=drift.severity, manual_review_reason="Creating/deleting interfaces is outside the supported remediation scope.",
                ))
                continue

            fields = {p for p in parts[2:]}  # only used for context; action reconciles managed fields in this interface
            commands = [f"interface {_quote_cli(name)}"]
            manual: list[str] = []
            if "ipv4_address" in spec or "ipv4_mask" in spec:
                wanted_ip = spec.get("ipv4_address")
                wanted_mask = spec.get("ipv4_mask")
                current_ip = current.get("ipv4_address")
                current_mask = current.get("ipv4_mask")
                if (wanted_ip, wanted_mask) != (current_ip, current_mask):
                    if wanted_ip and wanted_mask:
                        commands.append(f"ip address {_quote_cli(wanted_ip)} {_quote_cli(wanted_mask)}")
                        manual.append("Changing interface IP addressing can interrupt traffic or the management session.")
                    elif wanted_ip is None and wanted_mask is None:
                        commands.append("no ip address")
                        manual.append("Removing interface IPv4 addressing can interrupt traffic or management access.")
                    else:
                        manual.append("IPv4 address and mask must be declared together for safe remediation.")
            if "description" in spec and spec.get("description") != current.get("description"):
                if spec.get("description") is None or spec.get("description") == "":
                    commands.append("no description")
                else:
                    commands.append(f"description {_quote_cli(spec['description'])}")
            if "admin_state" in spec and str(spec["admin_state"]).lower() != str(current.get("admin_state", "up")).lower():
                commands.append("shutdown" if str(spec["admin_state"]).lower() == "down" else "no shutdown")
                manual.append("Changing administrative state can interrupt traffic or the management session.")
            if "access_groups" in spec:
                wanted_groups = spec.get("access_groups", {})
                current_groups = current.get("access_groups", {})
                changed_binding = False
                for direction, wanted_acl in wanted_groups.items():
                    if direction not in {"in", "out"}:
                        manual.append(f"Unsupported ACL binding direction '{direction}'.")
                        continue
                    current_acl = current_groups.get(direction)
                    if wanted_acl != current_acl:
                        changed_binding = True
                        if wanted_acl is None:
                            if current_acl is not None:
                                commands.append(f"no ip access-group {_quote_cli(current_acl)} {direction}")
                        else:
                            commands.append(f"ip access-group {_quote_cli(wanted_acl)} {direction}")
                if changed_binding:
                    manual.append("Changing an interface ACL binding can change reachability and requires review.")
            if len(commands) == 1 and not manual:
                continue
            actions.append(RemediationAction(
                path=f"interfaces.{name}", summary=f"Reconcile managed settings on {name}",
                commands=commands, severity=drift.severity,
                auto_applicable=not manual, requires_approval=True,
                manual_review_reason=" ".join(dict.fromkeys(manual)) or None,
            ))
            continue

        if len(parts) >= 2 and parts[0] == "acls":
            acl_name = parts[1]
            if acl_name in seen_acls:
                continue
            seen_acls.add(acl_name)
            wanted = desired.get("acls", {}).get(acl_name, {})
            observed = actual.get("acls", {}).get(acl_name, {})
            wanted_entries = wanted.get("entries", []) if isinstance(wanted, dict) else wanted
            actual_entries = observed.get("entries", []) if isinstance(observed, dict) else observed
            commands: list[str] = []
            if isinstance(wanted_entries, list):
                if acl_name.isdigit():
                    for entry in actual_entries if isinstance(actual_entries, list) else []:
                        if entry not in wanted_entries:
                            commands.append(f"no access-list {_quote_cli(acl_name)} {_quote_cli(entry)}")
                    for entry in wanted_entries:
                        if entry not in actual_entries:
                            commands.append(f"access-list {_quote_cli(acl_name)} {_quote_cli(entry)}")
                else:
                    acl_type = wanted.get("type", "extended") if isinstance(wanted, dict) else "extended"
                    commands.append(f"ip access-list {_quote_cli(acl_type)} {_quote_cli(acl_name)}")
                    commands.extend(f"no {_quote_cli(entry)}" for entry in (actual_entries if isinstance(actual_entries, list) else []))
                    commands.extend(_quote_cli(entry) for entry in wanted_entries)
                    commands.append("exit")
            actions.append(RemediationAction(
                path=f"acls.{acl_name}", summary=f"Reconcile ACL {acl_name}", commands=commands,
                severity="CRITICAL", auto_applicable=False, requires_approval=True,
                manual_review_reason="ACL order affects packet filtering. Review the command sequence and out-of-band access before applying.",
            ))
            continue

        if len(parts) >= 2 and parts[0] == "ospf":
            process_id = parts[1]
            if process_id not in seen_ospf:
                seen_ospf.add(process_id)
                actions.append(RemediationAction(
                    path=f"ospf.{process_id}", summary=f"Review OSPF process {process_id} drift",
                    severity="HIGH", auto_applicable=False, requires_approval=True,
                    manual_review_reason="OSPF changes can affect route propagation and adjacency; this version reports drift but does not auto-remediate routing policy.",
                ))
            continue

        actions.append(RemediationAction(
            path=drift.path, summary=f"Review drift at {drift.path}", severity=drift.severity,
            auto_applicable=False, requires_approval=True,
            manual_review_reason="No automatic remediation rule exists for this configuration path.",
        ))

    return actions

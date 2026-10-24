"""Load and validate desired-state YAML documents."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

import yaml

from netstate.exceptions import DesiredStateError

ALLOWED_TOP_LEVEL = {"hostname", "interfaces", "acls", "ospf", "strict"}
ALLOWED_INTERFACE_KEYS = {
    "ipv4_address", "ipv4_mask", "admin_state", "description", "access_groups"
}


def load_desired(path: str | Path) -> dict[str, Any]:
    """Read, parse, and validate the desired state from a YAML file."""
    target = Path(path)
    try:
        with target.open("r", encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except OSError as exc:
        raise DesiredStateError(f"Cannot read desired-state file '{target}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise DesiredStateError(f"Invalid YAML in '{target}': {exc}") from exc

    if not isinstance(document, dict):
        raise DesiredStateError("Desired-state YAML must contain a mapping at the top level.")
    unknown = set(document) - ALLOWED_TOP_LEVEL
    if unknown:
        raise DesiredStateError(f"Unsupported top-level key(s): {', '.join(sorted(unknown))}")

    for key in ("interfaces", "acls", "ospf"):
        if key in document and not isinstance(document[key], dict):
            raise DesiredStateError(f"'{key}' must be a YAML mapping.")

    if "hostname" in document and (not isinstance(document["hostname"], str) or not document["hostname"].strip()):
        raise DesiredStateError("'hostname' must be a non-empty string.")

    interfaces = document.get("interfaces", {})
    for name, spec in interfaces.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            raise DesiredStateError("Each interface must map a string name to a mapping.")
        unknown_keys = set(spec) - ALLOWED_INTERFACE_KEYS
        if unknown_keys:
            raise DesiredStateError(
                f"Unsupported key(s) for interface '{name}': {', '.join(sorted(unknown_keys))}"
            )
        if ("ipv4_address" in spec) != ("ipv4_mask" in spec):
            raise DesiredStateError(
                f"Interface '{name}' must declare ipv4_address and ipv4_mask together."
            )
        for ip_key in ("ipv4_address", "ipv4_mask"):
            if ip_key in spec and spec[ip_key] is not None:
                try:
                    ipaddress.IPv4Address(spec[ip_key])
                except (ipaddress.AddressValueError, TypeError) as exc:
                    raise DesiredStateError(f"Interface '{name}' has invalid {ip_key}: {spec[ip_key]}") from exc
        if "ipv4_address" in spec and ((spec["ipv4_address"] is None) != (spec["ipv4_mask"] is None)):
            raise DesiredStateError(
                f"Interface '{name}' must set both IPv4 address and mask to values or both to null."
            )
        if "admin_state" in spec and str(spec["admin_state"]).lower() not in {"up", "down"}:
            raise DesiredStateError(f"Interface '{name}' admin_state must be 'up' or 'down'.")
        if "description" in spec and spec["description"] is not None and not isinstance(spec["description"], str):
            raise DesiredStateError(f"Interface '{name}' description must be a string or null.")
        if "access_groups" in spec and not isinstance(spec["access_groups"], dict):
            raise DesiredStateError(f"Interface '{name}' access_groups must be a mapping such as {{in: '100'}}.")

    acls = document.get("acls", {})
    for acl_name, acl_spec in acls.items():
        if not isinstance(acl_name, (str, int)):
            raise DesiredStateError("ACL names must be strings or integers.")
        if isinstance(acl_spec, list):
            entries = acl_spec
        elif isinstance(acl_spec, dict):
            unknown_acl_keys = set(acl_spec) - {"type", "entries"}
            if unknown_acl_keys:
                raise DesiredStateError(f"Unsupported ACL key(s) for '{acl_name}': {', '.join(sorted(unknown_acl_keys))}")
            if acl_spec.get("type", "extended") not in {"standard", "extended"}:
                raise DesiredStateError(f"ACL '{acl_name}' type must be 'standard' or 'extended'.")
            entries = acl_spec.get("entries", [])
        else:
            raise DesiredStateError(f"ACL '{acl_name}' must be a list or mapping with 'entries'.")
        if not isinstance(entries, list) or any(not isinstance(entry, str) or not entry.strip() for entry in entries):
            raise DesiredStateError(f"ACL '{acl_name}' entries must be a list of non-empty strings.")

    ospf = document.get("ospf", {})
    for process_id, process in ospf.items():
        if not isinstance(process, dict):
            raise DesiredStateError(f"OSPF process '{process_id}' must be a mapping.")
        unknown_ospf_keys = set(process) - {"router_id", "networks"}
        if unknown_ospf_keys:
            raise DesiredStateError(
                f"Unsupported OSPF key(s) for process '{process_id}': {', '.join(sorted(unknown_ospf_keys))}"
            )
        if "router_id" in process:
            try:
                ipaddress.IPv4Address(process["router_id"])
            except (ipaddress.AddressValueError, TypeError) as exc:
                raise DesiredStateError(f"OSPF process '{process_id}' has invalid router_id.") from exc
        if "networks" in process:
            if not isinstance(process["networks"], list):
                raise DesiredStateError(f"OSPF process '{process_id}' networks must be a list.")
            for network in process["networks"]:
                if not isinstance(network, dict) or not {"network", "wildcard", "area"}.issubset(network):
                    raise DesiredStateError(
                        f"Each OSPF network in process '{process_id}' needs network, wildcard, and area."
                    )
                for key in ("network", "wildcard"):
                    try:
                        ipaddress.IPv4Address(network[key])
                    except (ipaddress.AddressValueError, TypeError) as exc:
                        raise DesiredStateError(f"Invalid OSPF {key}: {network.get(key)}") from exc

    if "strict" in document and not isinstance(document["strict"], bool):
        raise DesiredStateError("'strict' must be true or false.")

    if not any(key in document for key in ("hostname", "interfaces", "acls", "ospf")):
        raise DesiredStateError("Desired state must declare at least one of hostname, interfaces, acls, or ospf.")

    # Canonicalize keys/values used by the parser and comparison engine.
    normalized = dict(document)
    if "interfaces" in document:
        normalized["interfaces"] = {name: dict(spec) for name, spec in interfaces.items()}
    if "acls" in document:
        normalized["acls"] = {}
        for name, spec in acls.items():
            if isinstance(spec, list):
                normalized["acls"][str(name)] = {"type": "extended", "entries": [e.strip() for e in spec]}
            else:
                normalized["acls"][str(name)] = {
                    "type": spec.get("type", "extended"),
                    "entries": [e.strip() for e in spec.get("entries", [])],
                }
    if "ospf" in document:
        normalized["ospf"] = {str(pid): dict(p) for pid, p in ospf.items()}
    return normalized

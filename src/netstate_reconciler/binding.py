from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import NetworkIntent
from .topology import TopologyInventory

_INTERFACE_PREFIXES = {
    "gigabitethernet": "gigabitethernet",
    "gig": "gigabitethernet",
    "gi": "gigabitethernet",
    "fastethernet": "fastethernet",
    "fast": "fastethernet",
    "fa": "fastethernet",
    "tengigabitethernet": "tengigabitethernet",
    "ten": "tengigabitethernet",
    "te": "tengigabitethernet",
    "ethernet": "ethernet",
    "eth": "ethernet",
    "serial": "serial",
    "se": "serial",
    "port-channel": "port-channel",
    "portchannel": "port-channel",
    "po": "port-channel",
    "loopback": "loopback",
    "lo": "loopback",
    "vlan": "vlan",
    "vl": "vlan",
}


def normalize_interface_name(value: str) -> str:
    """Normalize common Cisco interface abbreviations for comparison only.

    The returned canonical form is not intended for CLI output. The discovered
    interface spelling must be retained when generating configuration.
    """
    compact = re.sub(r"\s+", "", str(value or "")).casefold()
    for prefix in sorted(_INTERFACE_PREFIXES, key=len, reverse=True):
        if compact.startswith(prefix):
            return _INTERFACE_PREFIXES[prefix] + compact[len(prefix):]
    return compact


def interfaces_for_device(inventory: TopologyInventory, device_name: str) -> list[str]:
    device = next((item for item in inventory.devices if item.name.casefold() == device_name.casefold()), None)
    values = set(device.interfaces if device else [])
    for link in inventory.links:
        if link.source.casefold() == device_name.casefold() and link.source_port:
            values.add(link.source_port)
        if link.target.casefold() == device_name.casefold() and link.target_port:
            values.add(link.target_port)
    return sorted(values, key=str.casefold)


def _router_interface_references(config: Any) -> list[str]:
    refs = set(config.interfaces.keys())
    for item in config.subinterfaces.values():
        refs.add(item.parent_interface)
    for acl in config.acls:
        base = acl.interface.rsplit(".", 1)[0] if "." in acl.interface and acl.interface.rsplit(".", 1)[1].isdigit() else acl.interface
        refs.add(base)
    return sorted(refs, key=str.casefold)


def interface_references(intent: NetworkIntent, logical_device: str) -> list[str]:
    if logical_device in intent.routers:
        return _router_interface_references(intent.routers[logical_device])
    if logical_device in intent.switches:
        config = intent.switches[logical_device]
        return sorted(
            {port.interface for port in [*config.access_ports, *config.trunk_ports]},
            key=str.casefold,
        )
    return []


def _interface_description(intent: NetworkIntent, logical_device: str, interface: str) -> str:
    router = intent.routers.get(logical_device)
    if router:
        if interface in router.interfaces:
            return router.interfaces[interface].description or ""
        base = interface.rsplit(".", 1)[0] if "." in interface else interface
        if base in router.interfaces:
            return router.interfaces[base].description or ""
    return ""


def _link_local_port(
    inventory: TopologyInventory, local_device: str, peer_device: str
) -> list[str]:
    ports: list[str] = []
    for link in inventory.links:
        if link.source.casefold() == local_device.casefold() and link.target.casefold() == peer_device.casefold():
            ports.append(link.source_port)
        elif link.target.casefold() == local_device.casefold() and link.source.casefold() == peer_device.casefold():
            ports.append(link.target_port)
    return [item for item in dict.fromkeys(ports) if item]


def suggest_interface_binding(
    intent: NetworkIntent,
    inventory: TopologyInventory,
    logical_device: str,
    actual_device: str,
    logical_interface: str,
    device_mapping: dict[str, str],
) -> str | None:
    """Suggest a physical interface using exact aliases and observed topology links.

    Suggestions are deliberately conservative: only a unique exact, description-
    peer, or uniquely connected router/switch link is returned.
    """
    candidates = interfaces_for_device(inventory, actual_device)
    if not candidates:
        return None

    canonical = normalize_interface_name(logical_interface)
    exact = [item for item in candidates if normalize_interface_name(item) == canonical]
    if len(exact) == 1:
        return exact[0]

    # Interface descriptions such as TRANSIT_TO_R2 and TRUNK_TO_SW1 encode an
    # intended peer. Resolve that peer against the operator's device-role map.
    description = _interface_description(intent, logical_device, logical_interface)
    if description:
        aliases = re.findall(r"(?:^|_)TO_([A-Za-z0-9_-]+)", description.upper())
        for alias in aliases:
            logical_peer = next((name for name in device_mapping if name.upper() == alias), None)
            actual_peer = device_mapping.get(logical_peer) if logical_peer else None
            if actual_peer:
                linked = _link_local_port(inventory, actual_device, actual_peer)
                if len(linked) == 1:
                    return linked[0]

    # For a switch uplink, a single physical connection to a mapped router is
    # unambiguous even when the logical intent uses a different port label.
    if logical_device in intent.switches:
        router_devices = {
            actual for logical, actual in device_mapping.items() if logical in intent.routers
        }
        linked_router_ports = sorted({
            port
            for router in router_devices
            for port in _link_local_port(inventory, actual_device, router)
        })
        switch_config = intent.switches[logical_device]
        is_trunk = any(
            normalize_interface_name(port.interface) == canonical
            for port in switch_config.trunk_ports
        )
        if is_trunk and len(linked_router_ports) == 1:
            return linked_router_ports[0]

    return None


def load_device_bindings(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"devices": {}, "interfaces": {}}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"devices": {}, "interfaces": {}}
    if not isinstance(payload, dict):
        return {"devices": {}, "interfaces": {}}
    devices = payload.get("devices") if isinstance(payload.get("devices"), dict) else {}
    interfaces = payload.get("interfaces") if isinstance(payload.get("interfaces"), dict) else {}
    return {"devices": devices, "interfaces": interfaces, "fingerprint": payload.get("fingerprint")}


def topology_fingerprint(inventory: TopologyInventory) -> str:
    """Fingerprint device identities and physical cabling, excluding volatile IP/interface state."""
    devices = sorted(
        (item.name, item.model, item.category) for item in inventory.devices
    )
    links = []
    for link in inventory.links:
        endpoint_a = (link.source, link.source_port)
        endpoint_b = (link.target, link.target_port)
        left, right = sorted((endpoint_a, endpoint_b), key=lambda item: (item[0].casefold(), item[1].casefold()))
        links.append((left, right, link.cable))
    payload = json.dumps({"devices": devices, "links": sorted(links)}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_device_bindings(
    path: str | Path, bindings: dict[str, Any], fingerprint: str | None = None
) -> Path:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "devices": bindings.get("devices", {}),
        "interfaces": bindings.get("interfaces", {}),
        "fingerprint": fingerprint or bindings.get("fingerprint"),
    }
    temp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        temp_path.chmod(0o600)
    except OSError:
        pass
    temp_path.replace(file_path)
    return file_path



def validate_device_bindings(
    intent: NetworkIntent, bindings: dict[str, Any], inventory: TopologyInventory
) -> list[str]:
    problems: list[str] = []
    device_map = bindings.get("devices", {})
    interface_map = bindings.get("interfaces", {})
    known_devices = {item.name.casefold(): item.name for item in inventory.devices}
    logical_names = (
        list(intent.routers) + list(intent.switches) + list(intent.hosts)
    )
    resolved: dict[str, str] = {}
    used: dict[str, str] = {}
    logical_roles = {}
    logical_roles.update({name: "router" for name in intent.routers})
    logical_roles.update({name: "switch" for name in intent.switches})
    logical_roles.update({name: "host" for name in intent.hosts})
    for logical_name in logical_names:
        requested = device_map.get(logical_name, logical_name)
        actual = known_devices.get(str(requested).casefold())
        if actual is None:
            problems.append(
                f"Device role `{logical_name}` is not mapped to a discovered device. "
                "Choose the matching device in Device & interface mapping."
            )
            continue
        resolved[logical_name] = actual
        record = next(item for item in inventory.devices if item.name.casefold() == actual.casefold())
        actual_role = record.category.casefold()
        model_hint = f"{record.model} {record.category}".casefold()
        expected_role = logical_roles[logical_name]
        incompatible = (
            (expected_role == "router" and ("switch" in model_hint or "2960" in model_hint or "3560" in model_hint))
            or (expected_role == "switch" and ("router" in model_hint or any(token in model_hint for token in ("1941", "2911", "2901", "4321", "4331"))))
            or (expected_role == "host" and ("router" in model_hint or "switch" in model_hint or "2960" in model_hint))
        )
        if actual_role in {"router", "switch", "host"} and actual_role != expected_role:
            incompatible = True
        if incompatible:
            problems.append(
                f"`{logical_name}` is a {expected_role} role but `{actual}` appears to be "
                f"a {actual_role if actual_role in {'router', 'switch', 'host'} else record.model}."
            )
        owner = used.get(actual.casefold())
        if owner:
            problems.append(
                f"Discovered device `{actual}` is assigned to both `{owner}` and `{logical_name}`."
            )
        else:
            used[actual.casefold()] = logical_name

    for logical_name in list(intent.routers) + list(intent.switches):
        actual_device = resolved.get(logical_name)
        if not actual_device:
            continue
        candidates = interfaces_for_device(inventory, actual_device)
        canonical = {normalize_interface_name(item): item for item in candidates}
        per_device = interface_map.get(logical_name, {})
        claimed_interfaces: dict[str, str] = {}
        for interface in interface_references(intent, logical_name):
            selected = per_device.get(interface)
            if selected:
                base = selected.rsplit(".", 1)[0] if "." in selected and selected.rsplit(".", 1)[1].isdigit() else selected
                normalized_selected = normalize_interface_name(base)
                if normalized_selected not in canonical:
                    problems.append(
                        f"{logical_name}: mapped interface `{selected}` is not present on `{actual_device}`."
                    )
                previous = claimed_interfaces.get(normalized_selected)
                if previous and previous != interface:
                    problems.append(
                        f"{logical_name}: `{previous}` and `{interface}` both map to `{selected}`. "
                        "Each configured physical port must have one logical binding."
                    )
                claimed_interfaces[normalized_selected] = interface

                # Interface descriptions can identify an expected peer. If live
                # links are available, ensure the chosen port really connects there.
                description = _interface_description(intent, logical_name, interface)
                peer_aliases = re.findall(r"(?:^|_)TO_([A-Za-z0-9_-]+)", description.upper()) if description else []
                for alias in peer_aliases:
                    logical_peer = next((name for name in device_map if name.upper() == alias), None)
                    actual_peer = device_map.get(logical_peer) if logical_peer else None
                    if actual_peer and inventory.links:
                        peer_ports = _link_local_port(inventory, actual_device, actual_peer)
                        if not peer_ports:
                            problems.append(
                                f"{logical_name}/{interface}: description expects a link to `{logical_peer}` "
                                f"({actual_peer}), but no such physical link was discovered."
                            )
                        elif not any(normalize_interface_name(port) == normalized_selected for port in peer_ports):
                            problems.append(
                                f"{logical_name}/{interface}: selected port `{selected}` is not the discovered "
                                f"link to `{logical_peer}`; Packet Tracer reports `{', '.join(peer_ports)}`."
                            )
            elif normalize_interface_name(interface) not in canonical:
                problems.append(
                    f"{logical_name}: interface `{interface}` has no mapping to a discovered interface "
                    f"on `{actual_device}`."
                )
    return problems


def bind_intent_to_inventory(
    intent: NetworkIntent,
    bindings: dict[str, Any],
    inventory: TopologyInventory,
) -> NetworkIntent:
    """Return a copy of an intent whose logical aliases resolve to live names.

    Device mappings translate YAML aliases to Packet Tracer display names.
    Interface mappings translate intent interface identifiers to the exact
    discovered interface spelling used by the target Packet Tracer device.
    """
    problems = validate_device_bindings(intent, bindings, inventory)
    if problems:
        raise ValueError("\n".join(problems))
    raw = intent.model_dump(mode="json")
    device_map = bindings.get("devices", {})
    interface_map = bindings.get("interfaces", {})
    available_devices = {item.name.casefold(): item.name for item in inventory.devices}

    logical_names = (
        list(raw.get("routers", {})) + list(raw.get("switches", {})) + list(raw.get("hosts", {}))
    )
    resolved: dict[str, str] = {}
    used: dict[str, str] = {}
    for logical_name in logical_names:
        actual_name = device_map.get(logical_name, logical_name)
        canonical_actual = available_devices.get(str(actual_name).casefold())
        if canonical_actual is None:
            raise ValueError(
                f"Device role `{logical_name}` is not mapped to a discovered device."
            )
        if canonical_actual.casefold() in used:
            raise ValueError(
                f"Discovered device `{canonical_actual}` is assigned to both "
                f"`{used[canonical_actual.casefold()]}` and `{logical_name}`."
            )
        used[canonical_actual.casefold()] = logical_name
        resolved[logical_name] = canonical_actual

    def mapped_interface(logical_device: str, value: str) -> str:
        per_device = interface_map.get(logical_device, {})
        # An explicit full subinterface binding takes precedence.
        if value in per_device:
            actual = per_device[value]
        else:
            base, dot, suffix = value.rpartition(".")
            lookup = base if dot and suffix.isdigit() else value
            actual = per_device.get(lookup)
            if actual is None:
                # Allow unchanged identifiers when their canonical aliases match
                # a discovered interface (Gig0/0 versus GigabitEthernet0/0).
                target_device = resolved[logical_device]
                candidates = interfaces_for_device(inventory, target_device)
                matches = [
                    candidate for candidate in candidates
                    if normalize_interface_name(candidate) == normalize_interface_name(lookup)
                ]
                if len(matches) == 1:
                    actual = matches[0]
                else:
                    raise ValueError(
                        f"{logical_device}: interface `{value}` has no saved binding to a "
                        f"discovered interface on `{target_device}`."
                    )
            if dot and suffix.isdigit():
                actual = f"{actual}.{suffix}"
        target_device = resolved[logical_device]
        candidates = interfaces_for_device(inventory, target_device)
        actual_base = actual.rsplit(".", 1)[0] if "." in actual and actual.rsplit(".", 1)[1].isdigit() else actual
        if not any(
            normalize_interface_name(candidate) == normalize_interface_name(actual_base)
            for candidate in candidates
        ):
            raise ValueError(
                f"{logical_device}: mapped interface `{actual_base}` is not present on "
                f"discovered device `{target_device}`."
            )
        return actual

    for section in ("routers", "switches", "hosts"):
        translated: dict[str, Any] = {}
        for logical_name, config in raw.get(section, {}).items():
            actual_name = resolved[logical_name]
            if section == "routers":
                config["interfaces"] = {
                    mapped_interface(logical_name, interface): value
                    for interface, value in config.get("interfaces", {}).items()
                }
                config["subinterfaces"] = {
                    mapped_interface(logical_name, interface): {
                        **value,
                        "parent_interface": mapped_interface(logical_name, value["parent_interface"]),
                    }
                    for interface, value in config.get("subinterfaces", {}).items()
                }
                for acl in config.get("acls", []):
                    acl["interface"] = mapped_interface(logical_name, acl["interface"])
            elif section == "switches":
                for port in config.get("access_ports", []):
                    port["interface"] = mapped_interface(logical_name, port["interface"])
                for port in config.get("trunk_ports", []):
                    port["interface"] = mapped_interface(logical_name, port["interface"])
            translated[actual_name] = config
        raw[section] = translated

    try:
        return NetworkIntent.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Mapped intent is invalid: {exc}") from exc

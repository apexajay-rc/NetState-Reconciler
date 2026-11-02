from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .mcp_client import result_text


@dataclass
class DeviceRecord:
    name: str
    model: str = "Unknown"
    category: str = "Unknown"
    interfaces: list[str] = field(default_factory=list)
    ip_addresses: list[str] = field(default_factory=list)


@dataclass
class LinkRecord:
    source: str
    source_port: str = ""
    target: str = ""
    target_port: str = ""
    cable: str = ""


@dataclass
class TopologyInventory:
    devices: list[DeviceRecord] = field(default_factory=list)
    links: list[LinkRecord] = field(default_factory=list)
    raw: Any = None

    @property
    def device_names(self) -> set[str]:
        return {device.name for device in self.devices}

    def to_dict(self) -> dict[str, Any]:
        return {"devices": [asdict(x) for x in self.devices], "links": [asdict(x) for x in self.links]}


def _to_object(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _to_object(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_object(item) for item in value]
    return value


def extract_payload(result: Any) -> Any:
    data = _to_object(result)
    if isinstance(data, dict):
        structured = data.get("structured") or data.get("structuredContent") or data.get("structured_content")
        if structured is not None:
            return structured
        raw = data.get("raw")
        if isinstance(raw, dict):
            structured = raw.get("structuredContent") or raw.get("structured_content")
            if structured is not None:
                return structured
        content = data.get("content") or (raw.get("content", []) if isinstance(raw, dict) else [])
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text = item["text"]
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    continue
        parsed = data.get("parsed_text")
        if parsed:
            return parsed[0]
    text = result_text(result)
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"unparsed_text": text}
    return data


def _find_key(value: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value and isinstance(value[key], (list, tuple)):
                return value[key]
        for nested in value.values():
            found = _find_key(nested, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_key(nested, keys)
            if found is not None:
                return found
    return None


def _first(item: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
    for key in keys:
        if item.get(key) not in (None, ""):
            return item[key]
    return default


def _category_for_model(model: str) -> str:
    value = model.lower()
    if any(token in value for token in ("router", "2911", "1941", "2901", "1841", "4321", "4331", "isr")):
        return "router"
    if "switch" in value or any(token in value for token in ("2960", "3560", "3650", "switch-")):
        return "switch"
    if any(token in value for token in ("pc", "server", "laptop", "ip phone")):
        return "host"
    if "power distribution" in value or "pdu" == value.strip():
        return "auxiliary"
    return "unknown"


def _candidate_texts(value: Any) -> list[str]:
    """Find textual MCP payloads, including MCP 0.10 structured `result` strings."""
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        # Prefer semantically meaningful MCP text fields before recursively
        # inspecting the full normalized result (which may duplicate content).
        for key in ("result", "text", "output", "message", "unparsed_text"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                found.append(candidate)
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                found.extend(_candidate_texts(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_candidate_texts(nested))
    # Preserve order while removing exact duplicates.
    return list(dict.fromkeys(text for text in found if text.strip()))


_DEVICE_LINE = re.compile(
    r"^\s*(?P<name>.+?)\s+\[(?P<model>[^\]]+)\]"
    r"(?:\s+@\s+\(-?\d+\s*,\s*-?\d+\))?"
    r"(?:\s+\((?P<interfaces>[^)]*)\))?\s*$"
)
_INTERFACE_LINE = re.compile(r"^\s{4,}(?P<name>[A-Za-z][A-Za-z0-9./:_-]*)\s+\[(?P<state>[^]]+)\]\s*$")
_LINK_LINE = re.compile(
    r"^\s*(?P<source>.+?):(?P<source_port>[A-Za-z][A-Za-z0-9./_-]*)"
    r"\s*<[-]+>\s*(?P<target>.+?):(?P<target_port>[A-Za-z][A-Za-z0-9./_-]*)\s*$"
)


def _parse_text_topology(text: str, raw: Any) -> TopologyInventory:
    """Parse the human-readable topology formats emitted by MCP 0.10.x.

    pt_export_topology emits a device block followed by connected interfaces
    and a `--- Links ---` section. pt_query_topology emits one device per line
    with an optional comma-separated interface list in parentheses.
    """
    devices_by_name: dict[str, DeviceRecord] = {}
    links: list[LinkRecord] = []
    current_device: DeviceRecord | None = None
    in_links = False

    for line in text.splitlines():
        if "--- Links ---" in line:
            in_links = True
            current_device = None
            continue
        if not line.strip():
            continue

        if in_links:
            link_match = _LINK_LINE.match(line)
            if link_match:
                groups = link_match.groupdict()
                links.append(LinkRecord(
                    source=groups["source"].strip(),
                    source_port=groups["source_port"],
                    target=groups["target"].strip(),
                    target_port=groups["target_port"],
                ))
            continue

        # Export interface rows also use square brackets (`[linked]`), so
        # recognize them before the more general device `[model]` pattern.
        interface_match = _INTERFACE_LINE.match(line)
        if interface_match and current_device is not None:
            current_device.interfaces = sorted(
                set(current_device.interfaces) | {interface_match.group("name")}
            )
            continue

        device_match = _DEVICE_LINE.match(line)
        if device_match:
            name = device_match.group("name").strip()
            model = device_match.group("model").strip()
            if not name or name.lower() in {"devices", "links"}:
                current_device = None
                continue
            interfaces = [
                part.strip() for part in (device_match.group("interfaces") or "").split(",")
                if part.strip()
            ]
            current_device = devices_by_name.get(name)
            if current_device is None:
                current_device = DeviceRecord(
                    name=name,
                    model=model,
                    category=_category_for_model(model),
                    interfaces=interfaces,
                )
                devices_by_name[name] = current_device
            else:
                if current_device.model == "Unknown" and model:
                    current_device.model = model
                if current_device.category == "unknown":
                    current_device.category = _category_for_model(model)
                current_device.interfaces = sorted(set(current_device.interfaces) | set(interfaces))
            continue

    return TopologyInventory(
        devices=sorted(devices_by_name.values(), key=lambda item: item.name.lower()),
        links=links,
        raw=raw,
    )


def merge_inventories(primary: TopologyInventory, supplemental: TopologyInventory) -> TopologyInventory:
    """Merge query/export views without discarding links or richer device metadata."""
    by_name = {device.name: device for device in primary.devices}
    for other in supplemental.devices:
        current = by_name.get(other.name)
        if current is None:
            by_name[other.name] = other
            continue
        if current.model == "Unknown" and other.model != "Unknown":
            current.model = other.model
        if current.category in {"unknown", ""} and other.category not in {"unknown", ""}:
            current.category = other.category
        current.interfaces = sorted(set(current.interfaces) | set(other.interfaces))
        current.ip_addresses = sorted(set(current.ip_addresses) | set(other.ip_addresses))
    links_by_key = {
        (link.source, link.source_port, link.target, link.target_port): link
        for link in primary.links
    }
    for link in supplemental.links:
        key = (link.source, link.source_port, link.target, link.target_port)
        links_by_key.setdefault(key, link)
    return TopologyInventory(
        devices=sorted(by_name.values(), key=lambda item: item.name.lower()),
        links=list(links_by_key.values()),
        raw={"primary": primary.raw, "supplemental": supplemental.raw},
    )


def parse_topology(result: Any) -> TopologyInventory:
    payload = extract_payload(result)
    device_items = _find_key(payload, ("devices", "nodes", "device_list")) or []
    link_items = _find_key(payload, ("links", "connections", "edges")) or []

    # MCP 0.10.x commonly returns a successful text result inside
    # structuredContent.result rather than structured device/link arrays.
    # Parse that documented human-readable representation before concluding
    # that discovery returned an empty inventory.
    if not device_items:
        for candidate in _candidate_texts(payload):
            if "Topology Export:" in candidate or re.search(r"DEVICES:\s*\d+\s*\|\s*LINKS:", candidate):
                parsed = _parse_text_topology(candidate, payload)
                if parsed.devices:
                    return parsed
        # Some normalized results keep the useful text outside `structured`.
        for candidate in _candidate_texts(result):
            if "Topology Export:" in candidate or re.search(r"DEVICES:\s*\d+\s*\|\s*LINKS:", candidate):
                parsed = _parse_text_topology(candidate, payload)
                if parsed.devices:
                    return parsed
    devices: list[DeviceRecord] = []
    for item in device_items:
        if isinstance(item, str):
            devices.append(DeviceRecord(name=item))
            continue
        if not isinstance(item, dict):
            continue
        name = str(_first(item, ("name", "device_name", "hostname", "label", "id")))
        if not name:
            continue
        interfaces_value = _first(item, ("interfaces", "ports", "port_list"), [])
        interface_names: list[str] = []
        addresses: list[str] = []
        if isinstance(interfaces_value, dict):
            for interface_name, details in interfaces_value.items():
                interface_names.append(str(interface_name))
                if isinstance(details, dict):
                    ip = _first(details, ("ip", "ip_address", "ipv4"))
                    if ip:
                        addresses.append(str(ip))
                elif isinstance(details, str) and re.match(r"\d+\.\d+\.\d+\.\d+", details):
                    addresses.append(details)
        elif isinstance(interfaces_value, list):
            for interface in interfaces_value:
                if isinstance(interface, str):
                    interface_names.append(interface)
                elif isinstance(interface, dict):
                    interface_name = str(_first(interface, ("name", "interface", "port", "id")))
                    if interface_name:
                        interface_names.append(interface_name)
                    ip = _first(interface, ("ip", "ip_address", "ipv4"))
                    if ip:
                        addresses.append(str(ip))
        direct_ip = _first(item, ("ip", "ip_address", "ipv4"))
        if direct_ip:
            addresses.append(str(direct_ip))
        devices.append(
            DeviceRecord(
                name=name,
                model=str(_first(item, ("model", "device_model", "type", "device_type"), "Unknown")),
                category=str(_first(item, ("category", "role", "kind"), "Unknown")),
                interfaces=sorted(set(interface_names)),
                ip_addresses=sorted(set(addresses)),
            )
        )

    links: list[LinkRecord] = []
    for item in link_items:
        if not isinstance(item, dict):
            continue
        source = str(_first(item, ("source", "from_device", "device_a", "src", "a")))
        target = str(_first(item, ("target", "destination", "to_device", "device_b", "dst", "b")))
        if not source and isinstance(item.get("endpoints"), list) and len(item["endpoints"]) == 2:
            source = str(item["endpoints"][0].get("device", "")) if isinstance(item["endpoints"][0], dict) else str(item["endpoints"][0])
            target = str(item["endpoints"][1].get("device", "")) if isinstance(item["endpoints"][1], dict) else str(item["endpoints"][1])
        if source and target:
            links.append(
                LinkRecord(
                    source=source,
                    source_port=str(_first(item, ("source_port", "from_port", "port_a", "interface_a"))),
                    target=target,
                    target_port=str(_first(item, ("target_port", "to_port", "port_b", "interface_b"))),
                    cable=str(_first(item, ("cable", "cable_type", "type"))),
                )
            )
    return TopologyInventory(devices=devices, links=links, raw=payload)

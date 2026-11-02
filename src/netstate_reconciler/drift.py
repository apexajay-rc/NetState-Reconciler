from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .topology import TopologyInventory


@dataclass
class Drift:
    category: str
    object_name: str
    expected: str
    observed: str


def compare_topology(baseline: dict[str, Any], current: TopologyInventory) -> list[Drift]:
    baseline_devices = {item["name"]: item for item in baseline.get("devices", [])}
    current_devices = {item.name: item for item in current.devices}
    drifts: list[Drift] = []
    for name in sorted(set(baseline_devices) - set(current_devices)):
        drifts.append(Drift("device_missing", name, "present", "missing"))
    for name in sorted(set(current_devices) - set(baseline_devices)):
        drifts.append(Drift("unexpected_device", name, "absent", "present"))
    for name in sorted(set(baseline_devices) & set(current_devices)):
        old_model = str(baseline_devices[name].get("model", "Unknown"))
        new_model = current_devices[name].model
        if old_model != new_model and old_model != "Unknown" and new_model != "Unknown":
            drifts.append(Drift("device_model_changed", name, old_model, new_model))
        old_ips = sorted(baseline_devices[name].get("ip_addresses", []))
        new_ips = sorted(current_devices[name].ip_addresses)
        if old_ips != new_ips:
            drifts.append(Drift("device_ip_changed", name, ", ".join(old_ips), ", ".join(new_ips)))
    def canonical_link(source: str, source_port: str, target: str, target_port: str) -> tuple[str, str, str, str]:
        left = (source, source_port)
        right = (target, target_port)
        first, second = sorted((left, right))
        return first[0], first[1], second[0], second[1]

    baseline_links = {
        canonical_link(link.get("source", ""), link.get("source_port", ""), link.get("target", ""), link.get("target_port", ""))
        for link in baseline.get("links", [])
    }
    current_links = {canonical_link(x.source, x.source_port, x.target, x.target_port) for x in current.links}
    for link in sorted(baseline_links - current_links):
        drifts.append(Drift("link_removed", f"{link[0]}:{link[1]} -> {link[2]}:{link[3]}", "present", "missing"))
    for link in sorted(current_links - baseline_links):
        drifts.append(Drift("link_added", f"{link[0]}:{link[1]} -> {link[2]}:{link[3]}", "absent", "present"))
    return drifts

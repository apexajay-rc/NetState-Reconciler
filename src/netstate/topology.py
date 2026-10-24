"""Topology-aware invariant checks over a small, explicit YAML schema."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from ipaddress import ip_address, ip_network
from typing import Any

@dataclass
class PolicyFinding:
    invariant: str
    severity: str
    message: str
    devices: list[str]
    def to_dict(self): return asdict(self)

def validate_topology(topology: dict[str, Any]) -> list[PolicyFinding]:
    """Validate address uniqueness, link endpoint references, and optional subnet reachability.

    Schema: devices: [{name, interfaces: [{name, ipv4_address, ipv4_mask}]}],
    links: [{a: 'R1/Gi0/0', b: 'SW1/Gi0/1'}]. This is deliberately not a full network solver.
    """
    findings: list[PolicyFinding] = []
    devices = topology.get("devices", [])
    known = {d.get("name") for d in devices if d.get("name")}
    seen_ips: dict[str, str] = {}
    endpoints = set()
    for d in devices:
        name = d.get("name", "<unnamed>")
        for iface in d.get("interfaces", []):
            ip = iface.get("ipv4_address")
            mask = iface.get("ipv4_mask", "255.255.255.0")
            if not ip or ip.lower() == "dhcp": continue
            try:
                network = ip_network(f"{ip}/{mask}", strict=False)
                ip_address(ip)
            except ValueError:
                findings.append(PolicyFinding("valid_interface_address", "HIGH", f"Invalid IPv4 address/mask on {name}/{iface.get('name')}: {ip}/{mask}", [name])); continue
            if ip in seen_ips:
                findings.append(PolicyFinding("unique_ip_addresses", "CRITICAL", f"Duplicate IP {ip} on {seen_ips[ip]} and {name}/{iface.get('name')}", [seen_ips[ip].split('/')[0], name]))
            else: seen_ips[ip] = f"{name}/{iface.get('name')}"
    for link in topology.get("links", []):
        for key in ("a", "b"):
            endpoint = link.get(key, "")
            dev = endpoint.split("/", 1)[0]
            if dev not in known:
                findings.append(PolicyFinding("link_endpoint_exists", "HIGH", f"Unknown link endpoint device: {endpoint}", [dev]))
            if endpoint in endpoints:
                findings.append(PolicyFinding("single_link_per_endpoint", "MEDIUM", f"Endpoint reused in multiple links: {endpoint}", [dev]))
            endpoints.add(endpoint)
    return findings

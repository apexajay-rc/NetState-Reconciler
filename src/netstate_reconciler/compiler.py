from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import IPv4Network

from .models import NetworkIntent, RouterIntent, SwitchIntent


INTERFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9./-]{1,39}$")
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
DEVICE_DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


def _ios_hostname(display_name: str) -> str:
    """Create a valid IOS hostname without changing the Packet Tracer target name."""
    if not DEVICE_DISPLAY_NAME_RE.fullmatch(display_name):
        raise CompileError(f"Invalid Packet Tracer device display name: {display_name!r}")
    hostname = re.sub(r"[^A-Za-z0-9-]+", "-", display_name).strip("-")
    hostname = re.sub(r"-+", "-", hostname)[:32]
    if not hostname or not hostname[0].isalnum():
        hostname = f"Device-{hostname}"[:32]
    return hostname


@dataclass(frozen=True)
class DeviceConfig:
    device: str
    role: str
    commands: tuple[str, ...]


class CompileError(ValueError):
    pass


def _check_interface(interface: str) -> str:
    if not INTERFACE_RE.fullmatch(interface):
        raise CompileError(f"Unsafe or invalid interface identifier: {interface!r}")
    return interface


def _wildcard(network: IPv4Network) -> str:
    return str(network.hostmask)


def _acl_address(value: str) -> tuple[str, str]:
    if value == "any":
        return "any", ""
    network = IPv4Network(value, strict=False)
    return str(network.network_address), str(network.hostmask)


def compile_router(name: str, config: RouterIntent, security: dict[str, str] | None = None) -> DeviceConfig:
    hostname = _ios_hostname(name)
    commands: list[str] = ["enable", "configure terminal", f"hostname {hostname}"]

    for interface_name, interface in config.interfaces.items():
        interface_name = _check_interface(interface_name)
        commands.extend([f"interface {interface_name}"])
        if interface.description:
            commands.append(f"description {interface.description.replace(chr(10), ' ').replace(chr(13), ' ')[:80]}")
        if interface.ipv4:
            commands.append(f"ip address {interface.ipv4.ip} {interface.ipv4.network.netmask}")
        commands.append("no shutdown" if interface.enabled else "shutdown")
        commands.append("exit")

    for subinterface_name, subinterface in config.subinterfaces.items():
        subinterface_name = _check_interface(subinterface_name)
        parent = _check_interface(subinterface.parent_interface)
        commands.extend([
            f"interface {parent}",
            "no shutdown",
            "exit",
            f"interface {subinterface_name}",
            f"encapsulation dot1Q {subinterface.vlan}",
        ])
        if subinterface.description:
            commands.append(f"description {subinterface.description.replace(chr(10), ' ').replace(chr(13), ' ')[:80]}")
        commands.extend([
            f"ip address {subinterface.ipv4.ip} {subinterface.ipv4.network.netmask}",
            "no shutdown" if subinterface.enabled else "shutdown",
            "exit",
        ])

    for scope in config.dhcp_scopes:
        for address in scope.excluded:
            commands.append(f"ip dhcp excluded-address {address}")
        commands.extend([f"ip dhcp pool {scope.name}", f"network {scope.network.network_address} {scope.network.netmask}"])
        commands.append(f"default-router {scope.default_router}")
        if scope.dns_server:
            commands.append(f"dns-server {scope.dns_server}")
        commands.append("exit")

    if config.ospf:
        commands.extend([f"router ospf {config.ospf.process_id}"])
        if config.ospf.router_id:
            commands.append(f"router-id {config.ospf.router_id}")
        for network in config.ospf.networks:
            commands.append(f"network {network.network_address} {_wildcard(network)} area {config.ospf.area}")
        commands.append("exit")

    for route in config.static_routes:
        commands.append(
            f"ip route {route.network.network_address} {route.network.netmask} "
            f"{route.next_hop} {route.administrative_distance}"
        )

    for acl in config.acls:
        interface_name = _check_interface(acl.interface)
        commands.append(f"ip access-list extended {acl.name}")
        for rule in acl.rules:
            source, source_wildcard = _acl_address(rule.source)
            destination, destination_wildcard = _acl_address(rule.destination)
            source_part = source if not source_wildcard else f"{source} {source_wildcard}"
            destination_part = destination if not destination_wildcard else f"{destination} {destination_wildcard}"
            line = f"{rule.action} {rule.protocol} {source_part} {destination_part}"
            if rule.destination_port is not None:
                line += f" eq {rule.destination_port}"
            commands.append(line)
        if acl.append_permit_any and not any(rule.action == "permit" and rule.source == "any" and rule.destination == "any" for rule in acl.rules):
            commands.append("permit ip any any")
        commands.extend(["exit", f"interface {interface_name}", f"ip access-group {acl.name} {acl.direction}", "exit"])

    if security is not None:
        username = security.get("username", "").strip()
        user_secret = security.get("user_secret", "")
        enable_secret = security.get("enable_secret", "")
        if not username or not user_secret:
            raise CompileError("SSH hardening requires both a management username and a user secret.")
        for secret_label, secret_value in (("user secret", user_secret), ("enable secret", enable_secret)):
            if secret_value and (not re.fullmatch(r"[A-Za-z0-9!@#$%^&*()_+=.,?-]{8,64}", secret_value)):
                raise CompileError(f"{secret_label.title()} must be 8–64 characters using the allowed printable set.")
        if username and user_secret:
            if not HOSTNAME_RE.fullmatch(username):
                raise CompileError("Management username contains unsupported characters")
            commands.extend([
                f"username {username} privilege 15 secret {user_secret}",
                "service password-encryption",
                "ip domain-name netstate.local",
                # Packet Tracer IOS prompts interactively for RSA modulus. Sending
                # an inline modulus in a bulk command list fails on common PT images.
                "ip ssh version 2",
                "line vty 0 4",
                "login local",
                "transport input ssh",
                "exec-timeout 5 0",
                "exit",
            ])
        if enable_secret:
            commands.append(f"enable secret {enable_secret}")

    commands.extend(["end", "write memory"])
    return DeviceConfig(device=name, role="router", commands=tuple(commands))


def compile_switch(name: str, config: SwitchIntent) -> DeviceConfig:
    hostname = _ios_hostname(name)
    commands: list[str] = ["enable", "configure terminal", f"hostname {hostname}"]
    for vlan in config.vlans:
        commands.extend([f"vlan {vlan.id}", f"name {vlan.name}", "exit"])
    for port in config.access_ports:
        interface = _check_interface(port.interface)
        commands.extend([
            f"interface {interface}",
            "switchport mode access",
            f"switchport access vlan {port.vlan}",
            "spanning-tree portfast" if port.portfast else "no spanning-tree portfast",
        ])
        if config.enable_port_security:
            commands.extend([
                "switchport port-security",
                f"switchport port-security maximum {config.port_security_max}",
                "switchport port-security violation restrict",
                "switchport port-security mac-address sticky",
            ])
        commands.append("exit")
    for port in config.trunk_ports:
        interface = _check_interface(port.interface)
        commands.extend([f"interface {interface}", "switchport mode trunk"])
        if port.allowed_vlans:
            allowed = ",".join(str(vlan) for vlan in port.allowed_vlans)
            commands.append(f"switchport trunk allowed vlan {allowed}")
        if port.native_vlan != 1:
            commands.append(f"switchport trunk native vlan {port.native_vlan}")
        commands.append("exit")
    commands.extend(["end", "write memory"])
    return DeviceConfig(device=name, role="switch", commands=tuple(commands))


def compile_intent(intent: NetworkIntent, security: dict[str, str] | None = None) -> list[DeviceConfig]:
    configs: list[DeviceConfig] = []
    for name, config in intent.routers.items():
        configs.append(compile_router(name, config, security))
    for name, config in intent.switches.items():
        configs.append(compile_switch(name, config))
    return configs


def compile_host_settings(intent: NetworkIntent) -> dict[str, dict[str, str]]:
    settings: dict[str, dict[str, str]] = {}
    for name, config in intent.hosts.items():
        if config.mode == "dhcp":
            settings[name] = {"mode": "dhcp"}
        else:
            assert config.ipv4 is not None
            assert config.gateway is not None
            settings[name] = {
                "mode": "static",
                "ip_address": str(config.ipv4.ip),
                "subnet_mask": str(config.ipv4.network.netmask),
                "gateway": str(config.gateway),
                "dns": str(config.dns_server or ""),
            }
    return settings

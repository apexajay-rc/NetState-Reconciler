from __future__ import annotations

from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InterfaceIntent(StrictModel):
    ipv4: IPv4Interface | None = None
    description: str | None = Field(default=None, max_length=80)
    enabled: bool = True


class SubinterfaceIntent(StrictModel):
    parent_interface: str = Field(min_length=2, max_length=40)
    vlan: int = Field(ge=1, le=4094)
    ipv4: IPv4Interface
    description: str | None = Field(default=None, max_length=80)
    enabled: bool = True


class StaticRoute(StrictModel):
    network: IPv4Network
    next_hop: IPv4Address
    administrative_distance: int = Field(default=1, ge=1, le=255)


class OSPFIntent(StrictModel):
    process_id: int = Field(default=1, ge=1, le=65535)
    router_id: IPv4Address | None = None
    networks: list[IPv4Network] = Field(default_factory=list)
    area: int = Field(default=0, ge=0, le=4294967295)


class DHCPScope(StrictModel):
    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    network: IPv4Network
    default_router: IPv4Address
    dns_server: IPv4Address | None = None
    excluded: list[IPv4Address] = Field(default_factory=list)

    @model_validator(mode="after")
    def gateway_in_subnet(self) -> "DHCPScope":
        if self.default_router not in self.network:
            raise ValueError("DHCP default_router must belong to the configured network")
        if any(address not in self.network for address in self.excluded):
            raise ValueError("All excluded DHCP addresses must belong to the configured network")
        return self


class ACLRule(StrictModel):
    action: Literal["permit", "deny"]
    protocol: Literal["ip", "icmp", "tcp", "udp"] = "ip"
    source: str = "any"
    destination: str = "any"
    destination_port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("source", "destination")
    @classmethod
    def valid_network_or_any(cls, value: str) -> str:
        from ipaddress import ip_network

        if value.lower() == "any":
            return "any"
        try:
            return str(ip_network(value, strict=False))
        except ValueError as exc:
            raise ValueError(f"Expected 'any' or a valid IPv4 network, got {value!r}") from exc

    @model_validator(mode="after")
    def port_requires_tcp_udp(self) -> "ACLRule":
        if self.destination_port is not None and self.protocol not in {"tcp", "udp"}:
            raise ValueError("destination_port is valid only for TCP or UDP rules")
        return self


class ACLIntent(StrictModel):
    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    interface: str = Field(min_length=2, max_length=40)
    direction: Literal["in", "out"] = "in"
    rules: list[ACLRule] = Field(min_length=1)
    append_permit_any: bool = True


class RouterIntent(StrictModel):
    interfaces: dict[str, InterfaceIntent] = Field(default_factory=dict)
    subinterfaces: dict[str, SubinterfaceIntent] = Field(default_factory=dict)
    ospf: OSPFIntent | None = None
    static_routes: list[StaticRoute] = Field(default_factory=list)
    dhcp_scopes: list[DHCPScope] = Field(default_factory=list)
    acls: list[ACLIntent] = Field(default_factory=list)


class VLANIntent(StrictModel):
    id: int = Field(ge=2, le=4094)
    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")


class AccessPortIntent(StrictModel):
    interface: str
    vlan: int = Field(ge=2, le=4094)
    portfast: bool = True


class TrunkPortIntent(StrictModel):
    interface: str
    allowed_vlans: list[int] = Field(default_factory=list)
    native_vlan: int = Field(default=1, ge=1, le=4094)


class SwitchIntent(StrictModel):
    vlans: list[VLANIntent] = Field(default_factory=list)
    access_ports: list[AccessPortIntent] = Field(default_factory=list)
    trunk_ports: list[TrunkPortIntent] = Field(default_factory=list)
    enable_port_security: bool = False
    port_security_max: int = Field(default=2, ge=1, le=16)

    @model_validator(mode="after")
    def referenced_vlans_exist(self) -> "SwitchIntent":
        vlan_ids = {vlan.id for vlan in self.vlans}
        for port in self.access_ports:
            if port.vlan not in vlan_ids:
                raise ValueError(f"Access port {port.interface} references undeclared VLAN {port.vlan}")
        for port in self.trunk_ports:
            missing = set(port.allowed_vlans) - vlan_ids
            if missing:
                raise ValueError(f"Trunk {port.interface} references undeclared VLANs: {sorted(missing)}")
        return self


class HostIntent(StrictModel):
    mode: Literal["dhcp", "static"] = "dhcp"
    ipv4: IPv4Interface | None = None
    gateway: IPv4Address | None = None
    dns_server: IPv4Address | None = None

    @model_validator(mode="after")
    def static_requires_address(self) -> "HostIntent":
        if self.mode == "static" and self.ipv4 is None:
            raise ValueError("Static host configuration requires ipv4, e.g. 192.168.10.10/24")
        if self.mode == "static" and self.gateway is None:
            raise ValueError("Static host configuration requires gateway")
        if self.mode == "static" and self.ipv4 is not None and self.gateway is not None:
            if self.gateway not in self.ipv4.network:
                raise ValueError("Static host gateway must belong to the host IPv4 subnet")
        return self


class NetworkIntent(StrictModel):
    name: str = Field(default="Packet-Tracer-Lab", min_length=1, max_length=64)
    routers: dict[str, RouterIntent] = Field(default_factory=dict)
    switches: dict[str, SwitchIntent] = Field(default_factory=dict)
    hosts: dict[str, HostIntent] = Field(default_factory=dict)
    management: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def at_least_one_device(self) -> "NetworkIntent":
        if not (self.routers or self.switches or self.hosts):
            raise ValueError("Intent must define at least one router, switch, or host")
        names = list(self.routers) + list(self.switches) + list(self.hosts)
        if len(names) != len(set(names)):
            raise ValueError("A device name cannot appear in more than one role")
        for name in names:
            valid_chars = all(ch.isalnum() or ch in "-_ ." for ch in name)
            if (
                not name or len(name) > 64 or not name[0].isalnum()
                or name != name.strip() or not valid_chars
            ):
                raise ValueError(f"Invalid device display name: {name!r}")

        assigned: dict[str, str] = {}
        for router_name, router in self.routers.items():
            for interface_name, interface in router.interfaces.items():
                if interface.ipv4:
                    address = str(interface.ipv4.ip)
                    if address in assigned:
                        raise ValueError(f"Duplicate IPv4 address {address}: {assigned[address]} and {router_name}/{interface_name}")
                    assigned[address] = f"{router_name}/{interface_name}"
            for interface_name, interface in router.subinterfaces.items():
                address = str(interface.ipv4.ip)
                if address in assigned:
                    raise ValueError(f"Duplicate IPv4 address {address}: {assigned[address]} and {router_name}/{interface_name}")
                assigned[address] = f"{router_name}/{interface_name}"
        for host_name, host in self.hosts.items():
            if host.ipv4:
                address = str(host.ipv4.ip)
                if address in assigned:
                    raise ValueError(f"Duplicate IPv4 address {address}: {assigned[address]} and {host_name}")
                assigned[address] = host_name

        scopes: list[tuple[str, DHCPScope]] = [
            (router_name, scope)
            for router_name, router in self.routers.items()
            for scope in router.dhcp_scopes
        ]
        for index, (router_name, scope) in enumerate(scopes):
            for other_router, other_scope in scopes[index + 1:]:
                if scope.network.overlaps(other_scope.network):
                    raise ValueError(
                        f"Overlapping DHCP scopes: {router_name}/{scope.name} ({scope.network}) and "
                        f"{other_router}/{other_scope.name} ({other_scope.network})"
                    )
        for host_name, host in self.hosts.items():
            if host.ipv4:
                for router_name, scope in scopes:
                    if host.ipv4.ip in scope.network and host.ipv4.ip not in scope.excluded:
                        raise ValueError(
                            f"Static host {host_name} address {host.ipv4.ip} is inside DHCP scope "
                            f"{scope.name} but is not excluded from its lease range"
                        )
        return self

from pathlib import Path

from netstate.parsers.ios import CiscoIOSParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_router_running_config():
    parser = CiscoIOSParser()
    state = parser.parse((FIXTURES / "router1_running.txt").read_text())
    assert state["hostname"] == "Router1"
    assert state["interfaces"]["GigabitEthernet0/0"]["ipv4_address"] == "192.168.1.1"
    assert state["interfaces"]["GigabitEthernet0/0"]["ipv4_mask"] == "255.255.255.0"
    assert state["interfaces"]["GigabitEthernet0/0"]["access_groups"] == {"in": "100"}
    assert state["interfaces"]["GigabitEthernet0/1"]["admin_state"] == "down"
    assert state["acls"]["100"]["type"] == "extended"
    assert state["acls"]["100"]["entries"] == [
        "permit ip 10.0.0.0 0.255.255.255 any", "deny ip any any log"
    ]
    assert state["ospf"]["1"]["router_id"] == "1.1.1.1"
    assert state["ospf"]["1"]["networks"] == [
        {"network": "192.168.1.0", "wildcard": "0.0.0.255", "area": "0"}
    ]
    assert not parser.warnings


def test_parse_named_acl_and_strip_sequence_numbers():
    state = CiscoIOSParser().parse((FIXTURES / "router1_named_acl.txt").read_text())
    assert state["acls"]["MGMT-FILTER"]["type"] == "extended"
    assert state["acls"]["MGMT-FILTER"]["entries"] == [
        "permit tcp 172.16.1.0 0.0.0.255 any eq 22", "deny ip any any log"
    ]


def test_secondary_ip_is_warned_and_does_not_replace_primary():
    parser = CiscoIOSParser()
    state = parser.parse("""hostname R1
interface GigabitEthernet0/0
 ip address 192.168.1.1 255.255.255.0
 ip address 192.168.2.1 255.255.255.0 secondary
!
""")
    interface = state["interfaces"]["GigabitEthernet0/0"]
    assert interface["ipv4_address"] == "192.168.1.1"
    assert parser.warnings


def test_unmodeled_security_relevant_interface_config_produces_warning():
    parser = CiscoIOSParser()
    parser.parse("""hostname R1
interface GigabitEthernet0/0
 ip address 192.168.1.1 255.255.255.0
 ip nat inside
!
""")
    assert any("outside the modeled subset" in warning for warning in parser.warnings)

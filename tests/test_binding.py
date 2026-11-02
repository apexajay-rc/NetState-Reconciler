from pathlib import Path

from netstate_reconciler.binding import (
    bind_intent_to_inventory,
    load_device_bindings,
    normalize_interface_name,
    save_device_bindings,
    suggest_interface_binding,
    topology_fingerprint,
    validate_device_bindings,
)
from netstate_reconciler.compiler import compile_intent
from netstate_reconciler.engine import validate_intent_against_inventory
from netstate_reconciler.intent import load_intent
from netstate_reconciler.topology import DeviceRecord, LinkRecord, TopologyInventory

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "config" / "intent.example.yaml"


def _inventory():
    return TopologyInventory(
        devices=[
            DeviceRecord("RouterA", "1941", "router", ["Gig0/0", "Gi0/1"]),
            DeviceRecord("RouterB", "1941", "router", ["Gi0/0", "Gi0/1"]),
            DeviceRecord("SwitchA", "2960-24TT", "switch", ["Gi0/1", "Fa0/1", "Fa0/2"]),
            DeviceRecord("SwitchB", "2960-24TT", "switch", ["Gi0/1", "Fa0/1"]),
            DeviceRecord("PC0", "PC-PT", "host", ["FastEthernet0"]),
            DeviceRecord("PC1", "PC-PT", "host", ["FastEthernet0"]),
            DeviceRecord("PC2", "PC-PT", "host", ["FastEthernet0"]),
        ],
        links=[
            LinkRecord("RouterA", "Gi0/0", "SwitchA", "Gi0/1"),
            LinkRecord("RouterA", "Gi0/1", "RouterB", "Gi0/0"),
            LinkRecord("RouterB", "Gi0/1", "SwitchB", "Gi0/1"),
            LinkRecord("PC0", "FastEthernet0", "SwitchA", "Fa0/1"),
            LinkRecord("PC1", "FastEthernet0", "SwitchA", "Fa0/2"),
            LinkRecord("PC2", "FastEthernet0", "SwitchB", "Fa0/1"),
        ],
    )


def _bindings():
    return {
        "devices": {
            "R1": "RouterA", "R2": "RouterB",
            "SW1": "SwitchA", "SW2": "SwitchB",
            "PC-EMPLOYEE": "PC0", "PC-GUEST": "PC1", "PC-FINANCE": "PC2",
        },
        "interfaces": {
            "R1": {"GigabitEthernet0/0": "Gi0/0", "GigabitEthernet0/1": "Gi0/1"},
            "R2": {"GigabitEthernet0/0": "Gi0/0", "GigabitEthernet0/1": "Gi0/1"},
            "SW1": {
                "FastEthernet0/1": "Fa0/1", "FastEthernet0/2": "Fa0/2",
                "GigabitEthernet0/1": "Gi0/1",
            },
            "SW2": {"FastEthernet0/1": "Fa0/1", "GigabitEthernet0/1": "Gi0/1"},
        },
    }


def test_normalize_common_cisco_interface_abbreviations():
    assert normalize_interface_name("GigabitEthernet0/0") == normalize_interface_name("Gi0/0")
    assert normalize_interface_name("FastEthernet0/1") == normalize_interface_name("Fa0/1")
    assert normalize_interface_name("TenGigabitEthernet1/0/1") == normalize_interface_name("Te1/0/1")


def test_binding_translates_device_aliases_and_interface_names():
    intent = load_intent(SAMPLE.read_text(encoding="utf-8"))
    inventory = _inventory()
    bound = bind_intent_to_inventory(intent, _bindings(), inventory)

    assert set(bound.routers) == {"RouterA", "RouterB"}
    assert set(bound.switches) == {"SwitchA", "SwitchB"}
    assert set(bound.hosts) == {"PC0", "PC1", "PC2"}
    assert "Gi0/0.10" in bound.routers["RouterA"].subinterfaces
    assert bound.routers["RouterA"].subinterfaces["Gi0/0.10"].parent_interface == "Gi0/0"
    assert bound.routers["RouterA"].acls[0].interface == "Gi0/0.20"
    assert bound.switches["SwitchA"].trunk_ports[0].interface == "Gi0/1"
    assert validate_intent_against_inventory(bound, inventory) == []
    configs = {item.device: item for item in compile_intent(bound)}
    assert "hostname RouterA" in configs["RouterA"].commands
    assert "interface Gi0/0.20" in configs["RouterA"].commands
    assert "interface Fa0/1" in configs["SwitchA"].commands


def test_binding_validation_reports_missing_device_and_interface_mappings():
    intent = load_intent(SAMPLE.read_text(encoding="utf-8"))
    errors = validate_device_bindings(intent, {"devices": {}, "interfaces": {}}, _inventory())
    assert any("R1" in error and "not mapped" in error for error in errors)


def test_topology_link_suggests_interface_using_description_peer():
    intent = load_intent(SAMPLE.read_text(encoding="utf-8"))
    suggestion = suggest_interface_binding(
        intent,
        _inventory(),
        "R1",
        "RouterA",
        "GigabitEthernet0/0",
        {"R1": "RouterA", "R2": "RouterB", "SW1": "SwitchA", "SW2": "SwitchB"},
    )
    assert suggestion == "Gi0/0"


def test_explicit_interface_binding_must_exist_on_selected_device():
    intent = load_intent(SAMPLE.read_text(encoding="utf-8"))
    bindings = _bindings()
    bindings["interfaces"]["R1"]["GigabitEthernet0/0"] = "Fa0/1"
    errors = validate_device_bindings(intent, bindings, _inventory())
    assert any("Fa0/1" in error and "RouterA" in error for error in errors)


def test_topology_fingerprint_ignores_link_direction_but_changes_when_cabling_changes():
    inventory = _inventory()
    same_topology = TopologyInventory(
        devices=inventory.devices,
        links=[
            LinkRecord(link.target, link.target_port, link.source, link.source_port, link.cable)
            for link in inventory.links
        ],
    )
    assert topology_fingerprint(inventory) == topology_fingerprint(same_topology)
    changed = TopologyInventory(
        devices=inventory.devices,
        links=inventory.links[:-1],
    )
    assert topology_fingerprint(inventory) != topology_fingerprint(changed)


def test_binding_rejects_interface_that_does_not_connect_to_declared_peer():
    intent = load_intent(SAMPLE.read_text(encoding="utf-8"))
    bindings = _bindings()
    bindings["interfaces"]["R1"]["GigabitEthernet0/0"] = "Gi0/1"
    errors = validate_device_bindings(intent, bindings, _inventory())
    assert any("does not connect" in error or "not the discovered link" in error for error in errors)


def test_packet_tracer_display_names_with_spaces_remain_targets_but_use_safe_ios_hostname():
    intent = load_intent("routers:\n  R1: {}\n")
    inventory = TopologyInventory(
        devices=[DeviceRecord("Core Router", "1941", "router", ["GigabitEthernet0/0"])],
        links=[],
    )
    mapped = bind_intent_to_inventory(
        intent,
        {"devices": {"R1": "Core Router"}, "interfaces": {}},
        inventory,
    )
    config = compile_intent(mapped)[0]
    assert config.device == "Core Router"
    assert "hostname Core-Router" in config.commands


def test_duplicate_interface_bindings_are_rejected():
    intent = load_intent(SAMPLE.read_text(encoding="utf-8"))
    bindings = _bindings()
    bindings["interfaces"]["SW1"]["FastEthernet0/2"] = "Fa0/1"
    errors = validate_device_bindings(intent, bindings, _inventory())
    assert any("both map to" in error for error in errors)


def test_device_bindings_persist_with_topology_fingerprint(tmp_path):
    path = tmp_path / "device-bindings.json"
    bindings = _bindings()
    fingerprint = topology_fingerprint(_inventory())
    save_device_bindings(path, bindings, fingerprint)
    restored = load_device_bindings(path)
    assert restored["devices"] == bindings["devices"]
    assert restored["interfaces"] == bindings["interfaces"]
    assert restored["fingerprint"] == fingerprint

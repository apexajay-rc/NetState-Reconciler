from netstate_reconciler.drift import compare_topology
from netstate_reconciler.topology import parse_topology


def test_parse_topology_from_structured_content():
    result = {
        "structured": {
            "devices": [
                {"name": "R1", "model": "2911", "interfaces": [{"name": "GigabitEthernet0/0", "ip": "10.0.0.1"}]},
                {"name": "SW1", "model": "2960-24TT", "interfaces": ["GigabitEthernet0/1"]},
            ],
            "links": [{"source": "R1", "source_port": "GigabitEthernet0/0", "target": "SW1", "target_port": "GigabitEthernet0/1"}],
        },
        "raw": {}, "text": "", "content": [], "parsed_text": [], "isError": False,
    }
    inventory = parse_topology(result)
    assert {device.name for device in inventory.devices} == {"R1", "SW1"}
    assert inventory.devices[0].interfaces == ["GigabitEthernet0/0"]
    assert len(inventory.links) == 1


def test_baseline_comparison_ignores_link_direction_and_detects_added_device():
    baseline = {
        "devices": [{"name": "R1", "model": "2911", "ip_addresses": []}, {"name": "SW1", "model": "2960", "ip_addresses": []}],
        "links": [{"source": "R1", "source_port": "Gi0/0", "target": "SW1", "target_port": "Gi0/1"}],
    }
    current = parse_topology({"structured": {"devices": [
        {"name": "R1", "model": "2911"}, {"name": "SW1", "model": "2960"}, {"name": "PC1", "model": "PC-PT"}],
        "links": [{"source": "SW1", "source_port": "Gi0/1", "target": "R1", "target_port": "Gi0/0"}]}})
    drifts = compare_topology(baseline, current)
    assert len(drifts) == 1
    assert drifts[0].category == "unexpected_device"


def _mcp_text_result(text: str):
    return {
        "isError": False,
        "structured": {"result": text},
        "content": [{"type": "text", "text": text}],
        "text": text,
        "parsed_text": [],
        "raw": {
            "content": [{"type": "text", "text": text}],
            "structuredContent": {"result": text},
            "isError": False,
        },
    }


def test_parse_packet_tracer_010_export_text_with_connected_interfaces_and_links():
    text = """=== Topology Export: 4 devices, 2 links ===

  Switch0 [2960-24TT] @ (460, 417)
    FastEthernet0/1 [linked]
    FastEthernet0/2 [linked]
  Power Distribution Device0 [Power Distribution Device] @ (3899, 3900)
  PC0 [PC-PT] @ (306, 226)
    FastEthernet0 [linked]
  PC1 [PC-PT] @ (538, 200)
    FastEthernet0 [linked]

--- Links ---
  PC0:FastEthernet0  <-->  Switch0:FastEthernet0/1
  PC1:FastEthernet0  <-->  Switch0:FastEthernet0/2"""
    inventory = parse_topology(_mcp_text_result(text))

    assert len(inventory.devices) == 4
    assert len(inventory.links) == 2
    by_name = {device.name: device for device in inventory.devices}
    assert by_name["Switch0"].model == "2960-24TT"
    assert by_name["Switch0"].category == "switch"
    assert by_name["Switch0"].interfaces == ["FastEthernet0/1", "FastEthernet0/2"]
    assert by_name["PC0"].category == "host"
    assert by_name["Power Distribution Device0"].category == "auxiliary"
    assert inventory.links[0].source == "PC0"
    assert inventory.links[0].source_port == "FastEthernet0"
    assert inventory.links[0].target == "Switch0"
    assert inventory.links[0].target_port == "FastEthernet0/1"


def test_parse_packet_tracer_010_query_text_with_full_interface_catalog():
    text = """DEVICES:4|LINKS:2

  Switch0              [2960-24TT]  (Vlan1,FastEthernet0/1,FastEthernet0/2,GigabitEthernet0/1)
  Power Distribution Device0 [Power Distribution Device]
  PC0                  [PC-PT]  (FastEthernet0,Bluetooth)
  PC1                  [PC-PT]  (FastEthernet0,Bluetooth)"""
    inventory = parse_topology(_mcp_text_result(text))
    by_name = {device.name: device for device in inventory.devices}

    assert len(inventory.devices) == 4
    assert inventory.links == []  # query output only reports the link count
    assert by_name["Switch0"].interfaces == ["Vlan1", "FastEthernet0/1", "FastEthernet0/2", "GigabitEthernet0/1"]
    assert by_name["PC0"].interfaces == ["FastEthernet0", "Bluetooth"]


def test_merge_export_and_query_views_preserves_links_and_full_interfaces():
    from netstate_reconciler.topology import merge_inventories

    export = parse_topology(_mcp_text_result("""=== Topology Export: 3 devices, 2 links ===
  Switch0 [2960-24TT] @ (460, 417)
    FastEthernet0/1 [linked]
    FastEthernet0/2 [linked]
  PC0 [PC-PT] @ (306, 226)
    FastEthernet0 [linked]
  PC1 [PC-PT] @ (538, 200)
    FastEthernet0 [linked]
--- Links ---
  PC0:FastEthernet0 <--> Switch0:FastEthernet0/1
  PC1:FastEthernet0 <--> Switch0:FastEthernet0/2"""))
    query = parse_topology(_mcp_text_result("""DEVICES:3|LINKS:2
  Switch0 [2960-24TT] (Vlan1,FastEthernet0/1,FastEthernet0/2,FastEthernet0/3)
  PC0 [PC-PT] (FastEthernet0,Bluetooth)
  PC1 [PC-PT] (FastEthernet0,Bluetooth)"""))
    merged = merge_inventories(export, query)
    by_name = {device.name: device for device in merged.devices}

    assert len(merged.devices) == 3
    assert len(merged.links) == 2
    assert "FastEthernet0/3" in by_name["Switch0"].interfaces
    assert by_name["Switch0"].model == "2960-24TT"


def test_engine_discovery_combines_export_links_with_query_interfaces(tmp_path):
    from netstate_reconciler.engine import NetStateEngine, StateStore

    export_text = """=== Topology Export: 4 devices, 2 links ===
  Switch0 [2960-24TT] @ (460, 417)
    FastEthernet0/1 [linked]
    FastEthernet0/2 [linked]
  Power Distribution Device0 [Power Distribution Device] @ (3899, 3900)
  PC0 [PC-PT] @ (306, 226)
    FastEthernet0 [linked]
  PC1 [PC-PT] @ (538, 200)
    FastEthernet0 [linked]
--- Links ---
  PC0:FastEthernet0 <--> Switch0:FastEthernet0/1
  PC1:FastEthernet0 <--> Switch0:FastEthernet0/2"""
    query_text = """DEVICES:4|LINKS:2
  Switch0 [2960-24TT] (Vlan1,FastEthernet0/1,FastEthernet0/2,FastEthernet0/3)
  Power Distribution Device0 [Power Distribution Device]
  PC0 [PC-PT] (FastEthernet0,Bluetooth)
  PC1 [PC-PT] (FastEthernet0,Bluetooth)"""

    class FakeToolbox:
        def has(self, *names):
            return next((name for name in names if name in {"pt_export_topology", "pt_query_topology"}), None)

        def invoke(self, name, semantic=None):
            return _mcp_text_result(export_text if name == "pt_export_topology" else query_text)

    engine = NetStateEngine(FakeToolbox(), StateStore(tmp_path / "state"))
    inventory = engine.discover()
    by_name = {device.name: device for device in inventory.devices}

    assert len(inventory.devices) == 4
    assert len(inventory.links) == 2
    assert "FastEthernet0/3" in by_name["Switch0"].interfaces
    assert by_name["Power Distribution Device0"].category == "auxiliary"
    assert set(inventory.raw) == {"pt_export_topology", "pt_query_topology", "discovery_errors"}


def test_parse_exact_user_mcp_0102_export_and_query_payloads():
    export_text = """=== Topology Export: 4 devices, 2 links ===

  Switch0 [2960-24TT] @ (460, 417)
    FastEthernet0/1 [linked]
    FastEthernet0/2 [linked]
  Power Distribution Device0 [Power Distribution Device] @ (3899, 3900)
  PC0 [PC-PT] @ (306, 226)
    FastEthernet0 [linked]
  PC1 [PC-PT] @ (538, 200)
    FastEthernet0 [linked]

--- Links ---
  PC0:FastEthernet0  <-->  Switch0:FastEthernet0/1
  PC1:FastEthernet0  <-->  Switch0:FastEthernet0/2"""
    query_text = """DEVICES:4|LINKS:2

  Switch0              [2960-24TT]  (Vlan1,FastEthernet0/1,FastEthernet0/2,FastEthernet0/3,FastEthernet0/4,FastEthernet0/5,FastEthernet0/6,FastEthernet0/7,FastEthernet0/8,FastEthernet0/9,FastEthernet0/10,FastEthernet0/11,FastEthernet0/12,FastEthernet0/13,FastEthernet0/14,FastEthernet0/15,FastEthernet0/16,FastEthernet0/17,FastEthernet0/18,FastEthernet0/19,FastEthernet0/20,FastEthernet0/21,FastEthernet0/22,FastEthernet0/23,FastEthernet0/24,GigabitEthernet0/1,GigabitEthernet0/2)
  Power Distribution Device0 [Power Distribution Device]
  PC0                  [PC-PT]  (FastEthernet0,Bluetooth)
  PC1                  [PC-PT]  (FastEthernet0,Bluetooth)"""

    export = _mcp_text_result(export_text)
    query = _mcp_text_result(query_text)
    from netstate_reconciler.topology import merge_inventories

    merged = merge_inventories(parse_topology(export), parse_topology(query))
    by_name = {item.name: item for item in merged.devices}

    assert set(by_name) == {"Switch0", "Power Distribution Device0", "PC0", "PC1"}
    assert len(merged.links) == 2
    assert by_name["Switch0"].category == "switch"
    assert len(by_name["Switch0"].interfaces) == 27
    assert by_name["PC0"].category == "host"
    assert by_name["Power Distribution Device0"].category == "auxiliary"


def test_engine_preserves_discovery_diagnostic_when_inventory_is_empty(tmp_path):
    from netstate_reconciler.engine import NetStateEngine, StateStore
    from netstate_reconciler.mcp_client import MCPToolError

    class EmptyToolbox:
        def has(self, *names):
            return next((name for name in names if name in {"pt_export_topology", "pt_query_topology"}), None)

        def invoke(self, name, semantic=None):
            return _mcp_text_result("No devices are currently present in the workspace.")

    engine = NetStateEngine(EmptyToolbox(), StateStore(tmp_path / "state"))
    try:
        engine.discover()
    except MCPToolError:
        pass
    else:
        raise AssertionError("Discovery should reject an empty inventory")

    diagnostic = engine.last_discovery_diagnostic
    assert diagnostic is not None
    assert diagnostic["status"] == "empty_inventory"
    assert diagnostic["merged_devices"] == 0
    assert "pt_export_topology" in diagnostic["raw"]
    assert "pt_query_topology" in diagnostic["raw"]

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from netstate_reconciler.mcp_client import MCPHTTPClient, MCPToolbox, result_text  # noqa: E402
from netstate_reconciler.topology import merge_inventories, parse_topology  # noqa: E402


def port_open(host: str, port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(1.0)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose the NetState ↔ Packet Tracer MCP connection.")
    parser.add_argument("--endpoint", default="http://127.0.0.1:39400/mcp")
    parser.add_argument("--bridge-port", type=int, default=54321)
    args = parser.parse_args()
    client = MCPHTTPClient(args.endpoint, timeout=20)
    toolbox = MCPToolbox(client)
    try:
        tools = toolbox.refresh()
    except Exception as exc:
        print(f"MCP endpoint: FAILED — {exc}")
        return 2

    print(f"MCP endpoint: reachable ({args.endpoint})")
    print(f"MCP tools: {len(tools)}")
    names = set(tool.name for tool in tools)
    expected = [
        "pt_bridge_status", "pt_export_topology", "pt_query_topology", "pt_cli",
        "pt_host_ip_config", "pt_verify_connectivity", "pt_audit_security",
        "pt_backup_config", "pt_save_project", "pt_read_packet_trace",
    ]
    for name in expected:
        print(f"  {'OK' if name in names else 'MISSING':7} {name}")

    print(f"Bridge port 127.0.0.1:{args.bridge_port}: {'LISTENING' if port_open('127.0.0.1', args.bridge_port) else 'NOT LISTENING'}")
    if "pt_bridge_status" in names:
        try:
            result = toolbox.invoke("pt_bridge_status")
            print("Bridge status response:")
            print(result_text(result) or json.dumps(result, indent=2, default=str))
        except Exception as exc:
            print(f"Bridge status tool: FAILED — {exc}")

    export_inventory = None
    query_inventory = None
    for tool_name, label in (("pt_export_topology", "Topology export"), ("pt_query_topology", "Topology query")):
        if tool_name not in names:
            print(f"{label}: tool unavailable")
            continue
        try:
            raw_result = toolbox.invoke(tool_name)
            parsed = parse_topology(raw_result)
            print(f"{label}: parsed {len(parsed.devices)} devices and {len(parsed.links)} links")
            print(f"{label} response:")
            print(result_text(raw_result) or json.dumps(raw_result, indent=2, default=str))
            if tool_name == "pt_export_topology":
                export_inventory = parsed
            else:
                query_inventory = parsed
        except Exception as exc:
            print(f"{label}: FAILED — {exc}")

    if export_inventory and query_inventory:
        inventory = merge_inventories(export_inventory, query_inventory)
    else:
        inventory = export_inventory or query_inventory
    if inventory:
        print(f"\nNetState parser result: {len(inventory.devices)} devices, {len(inventory.links)} links")
        for device in inventory.devices:
            print(f"  {device.name} [{device.model}] category={device.category} interfaces={len(device.interfaces)}")
        for link in inventory.links:
            print(f"  LINK {link.source}:{link.source_port} <-> {link.target}:{link.target_port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

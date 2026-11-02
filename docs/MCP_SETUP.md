# Packet Tracer MCP setup

## Pinned compatibility target

This project targets:

- `packet-tracer-mcp==0.10.2`
- MCP Control Center V6 extension (`MCP-Control-Center.pts` from the upstream release assets)
- Python 3.11+
- Packet Tracer 9.0 recommended

The upstream v0.10.0 release introduced the V6 extension and changed the Streamable HTTP transport from port 39000 to **39400**. The newer release notes describe V6's in-extension activity panel and its Script Engine core. The current v0.10.2 release includes fixes for DHCP static-host exclusions, post-STP DHCP renewals and health-check detection of cabled hosts without IP addresses.

References:

- https://github.com/Mats2208/MCP-Packet-Tracer/releases
- https://mats2208.github.io/MCP-Packet-Tracer/installation/
- https://mats2208.github.io/MCP-Packet-Tracer/live-deploy/

## Install matching extension

1. Fully exit Cisco Packet Tracer. Packet Tracer scans script modules at startup.
2. Open the upstream releases page and download the V6 `MCP-Control-Center.pts` asset from the v0.10.x release.
3. Start Packet Tracer.
4. Navigate to **Extensions → Scripting → Configure PT Script Modules → Add**.
5. Select the `.pts` file and confirm.
6. Open **Extensions → MCP BUILDER**.
7. Confirm the MCP Control Center reports an active/connected bridge.

The menu entry remains labelled MCP BUILDER even though the installed module asset is MCP-Control-Center.pts.

## Ports

| Port | Service | Purpose |
|---|---|---|
| 39400 | Python MCP server | Streamable HTTP endpoint: `http://127.0.0.1:39400/mcp` |
| 54321 | MCP Control Center bridge | Internal HTTP bridge between the MCP server and Packet Tracer extension |

Port 39000 belongs to Packet Tracer's own IPC use in the v0.10.1+ release notes. Do not reuse the older v0.9.0 HTTP endpoint setting (`:39000/mcp`) with this project.

## Start services

NetState's `start_netstate.sh` starts the HTTP MCP server with:

```bash
python -m packet_tracer_mcp
```

It waits for port 39400, attempts to launch Packet Tracer, then starts Streamlit. The extension itself still needs to be enabled in Packet Tracer and the MCP BUILDER panel must be opened. The launcher cannot guarantee activation of Packet Tracer's internal extension UI.

Manual server start for diagnostics:

```bash
cd ~/NetState-Reconciler
source .venv/bin/activate
python -u -m packet_tracer_mcp
```

Check the ports:

```bash
ss -ltnp | grep -E ':(39400|54321)\\b' || true
```

A listener on 39400 confirms the MCP HTTP server is accepting connections. A listener on 54321 and a positive `pt_bridge_status` response are needed for the bridge. Do not infer bridge health from the MCP port alone.

The upstream PyPI platform matrix currently marks Linux server and live-deploy support as not tested. This final project targets Ubuntu because that is the development environment, but its local live bridge must be validated on the actual machine before the demonstration. The package works through loopback HTTP in the intended design; that is not a substitute for a successful Packet Tracer integration test.

## Ubuntu note

The MCP package documents Python 3.11+ and Packet Tracer 8.2+ (tested on Packet Tracer 9.0). Release notes describe live verification on macOS and Windows 11 for v0.10.0; the target Ubuntu desktop combination must still be validated locally. If bridge polling or Script Engine IPC fails on Ubuntu, retain the raw `pt_bridge_status` result and both service logs rather than upgrading versions blindly.

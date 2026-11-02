# Windows 10/11 setup

This guide describes a native PowerShell installation. The project was primarily developed and tested on Ubuntu; follow the live-connection checks below before using Windows for a demonstration. The upstream `packet-tracer-mcp` package documents Windows 11 support, but that does not by itself prove that this complete NetState build works on every Windows/Packet Tracer combination.

## Prerequisites

- Windows 10/11 (Windows 11 recommended).
- Python 3.11 or newer. Install from [python.org](https://www.python.org/downloads/windows/) and enable **Add python.exe to PATH**. The Python Launcher (`py`) is recommended.
- Git for Windows, if cloning.
- Graphviz. Install with `winget install -e --id Graphviz.Graphviz`, or use the [official Windows installer](https://graphviz.org/download/). Reopen PowerShell after installing and confirm `dot -V` works.
- Cisco Packet Tracer 8.2 or newer; Packet Tracer 9.0 is recommended for this MCP target.

## Install NetState

Open PowerShell:

```powershell
git clone https://github.com/apexajay-rc/NetState-Reconciler.git
Set-Location .\NetState-Reconciler
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip wheel
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
New-Item -ItemType Directory -Force -Path @(
    ".netstate\checkpoints",
    ".netstate\reports",
    ".netstate\snapshots",
    "logs"
) | Out-Null
```

If `py -3.11` is not the installed interpreter version, use the version you installed (3.11 or newer). You do not need to activate the virtual environment; use `.\.venv\Scripts\python.exe` for the commands below. If you do activate it and PowerShell blocks `Activate.ps1`, either use the direct executable or set a process-only execution policy with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

## Install the Packet Tracer extension

The Python MCP server and the Packet Tracer `.pts` extension are separate components.

1. Download the extension version compatible with `packet-tracer-mcp==0.10.2` from the [upstream releases](https://github.com/Mats2208/MCP-Packet-Tracer/releases); consult [`MCP_SETUP.md`](MCP_SETUP.md) for the compatibility target used by this project.
2. Fully exit Packet Tracer.
3. Reopen Packet Tracer and select **Extensions → Scripting → Configure PT Script Modules → Add**.
4. Select the downloaded `.pts` file and confirm.
5. Enable the detected script module if Packet Tracer prompts you; restart Packet Tracer if required.
6. Open **Extensions → MCP BUILDER** and confirm that the bridge reports connected.

## Run NetState (two PowerShell windows)

### Window 1 — MCP HTTP server

From the project directory:

```powershell
.\.venv\Scripts\python.exe -u -m packet_tracer_mcp
```

Keep this window open. The expected MCP endpoint is `http://127.0.0.1:39400/mcp`.

### Window 2 — Streamlit application

From the same project directory:

```powershell
$env:NETSTATE_MCP_ENDPOINT = "http://127.0.0.1:39400/mcp"
$env:NETSTATE_PORT = "8501"
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

Open <http://127.0.0.1:8501> in your browser. Keep Packet Tracer open with the MCP BUILDER extension loaded. In NetState, click **Connect & inspect MCP**, then discover the live topology.

## Verify and stop

In a third PowerShell window, check the two local ports:

```powershell
Test-NetConnection 127.0.0.1 -Port 39400
Test-NetConnection 127.0.0.1 -Port 54321
```

The 39400 listener confirms that the Python MCP HTTP server is listening. It does not establish that Packet Tracer is connected; also check the MCP BUILDER panel and NetState's bridge/tool diagnostics.

To stop the services, press **Ctrl+C** in the Streamlit window and then in the MCP server window. Packet Tracer can remain open.

## Common problems

- **`py` or `python` not found:** reinstall Python and enable PATH integration, or use the full path to the Python executable.
- **`dot` not found:** install Graphviz and ensure its `bin` directory is on `PATH`; reopen PowerShell.
- **No module named `packet_tracer_mcp`:** install dependencies using the `.venv` Python shown above, and run the MCP server with that same executable.
- **MCP endpoint listens but inventory is empty:** confirm the extension is enabled, Packet Tracer is open, MCP BUILDER is open, and the bridge reports connected.
- **Port 39400 is occupied:** identify the owning process before stopping it. Do not terminate an unrelated service.
- **IOS command fails:** inspect the exact simulator CLI error. Packet Tracer command support varies by device and IOS image. Do not blindly replay a multi-device configuration transaction after a partial failure.

## Important platform note

The repository's `install.sh`, `start_netstate.sh`, and `stop_netstate.sh` are Bash scripts for Linux and are not PowerShell scripts. On Windows, use the native Python/PowerShell commands in this document. Successful Python package installation is not proof of live Packet Tracer bridge integration; perform the verification steps on the machine where the project will run.

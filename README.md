# NetState Reconciler

**Desired-state configuration drift detection and remediation for Cisco Packet Tracer labs.**

NetState Reconciler discovers a Packet Tracer topology, maps logical network roles to the devices and interfaces that actually exist, compares selected live configuration state with a saved desired state, and guides an operator through a narrow remediation and read-back verification workflow.

> **Current scope (1.2.0):** the first semantic reconciliation control covers named router ACL attachments. It is an educational lab demonstrator, not a vendor-independent network automation platform or a complete IOS configuration verifier.

## What it does

- Discovers Packet Tracer devices, interfaces, IP information and physical links through the Packet Tracer MCP integration.
- Supports capability-aware topology planning where compatible MCP planning/deployment tools are available.
- Maps logical intent roles (such as `R1`, `SW1`, or `PC-GUEST`) to the actual discovered Packet Tracer device names.
- Resolves logical interface references to discovered physical interfaces, including common Cisco interface abbreviations.
- Uses YAML to describe a supported desired network configuration: router interfaces and subinterfaces, OSPF, static routes, DHCP scopes, ACLs, VLANs, switch access/trunk ports, basic port security and host IPv4 settings.
- Shows generated configuration plans and requires operator approval before live changes.
- Saves local checkpoints where the MCP server supports them and stops a multi-device execution after a recognised command failure.
- Saves a desired-state baseline and compares it with fresh live router configuration for the supported ACL-attachment control.
- Simulates removal of a selected ACL attachment after precondition checks and explicit operator approval.
- Generates a minimal ACL reattachment command and reports `VERIFIED` only when a fresh running-config read-back confirms the intended attachment.
- Provides reachability, security-posture and topology-drift utilities as supporting diagnostic features.

## Current reconciliation scope and limitations

Version 1.2.0 semantically detects and reconciles **named IPv4 ACL attachments on router interfaces**. It can identify a missing or incorrect `ip access-group <name> in|out` attachment, provided the relevant interface and ACL definition can be read from the device configuration. Automatic repair is refused when required evidence is missing or incomplete.

The following are **not yet covered by the semantic reconciler**: VLAN membership, trunk allowed-VLAN lists, DHCP scopes, OSPF, static routes, switch port security, host addressing, and arbitrary IOS commands. Topology and redacted running-config snapshots can be compared as supporting evidence, but a textual diff is not the same as semantic verification. Do not interpret an unsupported field as compliant.

Packet Tracer's IOS command support varies by model and simulated IOS version. The project does not claim atomic multi-device rollback. A submitted command is not proof of application; fresh read-back and appropriate connectivity checks are required.

## Requirements

### Common requirements

- Python 3.11 or newer.
- Cisco Packet Tracer 8.2 or newer (Packet Tracer 9.0 is recommended for the pinned MCP integration).
- Packet Tracer MCP server `packet-tracer-mcp==0.10.2` and its matching MCP Control Center extension.
- A manually created Packet Tracer topology, or compatible topology builder tools exposed by the installed MCP server.

The MCP HTTP endpoint defaults to `http://127.0.0.1:39400/mcp`. The Packet Tracer bridge is a separate service, normally on port `54321`. The application discovers the runtime tool catalog; availability of individual tools depends on the installed MCP server and extension versions.

### Platform status

- **Ubuntu/Linux:** the project's primary development and tested environment. Use the Bash scripts documented below.
- **Windows 10/11:** native PowerShell installation and manual startup instructions are provided in this README and [`docs/WINDOWS_SETUP.md`](docs/WINDOWS_SETUP.md). The upstream Packet Tracer MCP package documents Windows 11 support, but the complete NetState + Packet Tracer live workflow has not yet been independently acceptance-tested by this project on Windows. Verify the MCP bridge and live topology on the target machine before relying on it for a demo.

## Installation (Ubuntu/Linux)

Install system prerequisites:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip graphviz git
```

Clone the repository and install dependencies:

```bash
git clone https://github.com/apexajay-rc/NetState-Reconciler.git
cd NetState-Reconciler
chmod +x install.sh start_netstate.sh stop_netstate.sh
./install.sh
```

The installer creates a project-local `.venv` and installs the project plus development dependencies. The Packet Tracer MCP Control Center extension is installed inside Packet Tracer; see [`docs/MCP_SETUP.md`](docs/MCP_SETUP.md).

## Installation (Windows 10/11)

Run these commands in **PowerShell** (Windows Terminal is suitable). Do not use the `.sh` scripts from native PowerShell; those scripts are for Linux/Bash.

### 1. Install prerequisites

Install:

- Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/). During setup, enable **Add python.exe to PATH**. The Python Launcher (`py`) is useful for selecting a specific Python version.
- Git for Windows from [git-scm.com](https://git-scm.com/download/win), if you plan to clone the repository.
- Graphviz. With Windows Package Manager:

  ```powershell
  winget install -e --id Graphviz.Graphviz
  ```

  Alternatively, use the official [Graphviz Windows installer](https://graphviz.org/download/). After installation, close and reopen PowerShell, then confirm `dot -V` works.
- Cisco Packet Tracer. Packet Tracer 9.0 is recommended for this project.

Verify the tools:

```powershell
py -3.11 --version
git --version
dot -V
```

If your Python installation is newer than 3.11, replace `-3.11` with the installed supported version. Python 3.11+ is required.

### 2. Clone the repository

```powershell
git clone https://github.com/apexajay-rc/NetState-Reconciler.git
Set-Location .\NetState-Reconciler
```

You can also download the repository ZIP from GitHub and extract it; Git is only required for cloning and later updates.

### 3. Create the virtual environment and install dependencies

```powershell
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

This uses the virtual environment's Python directly, so PowerShell script-execution policy changes are not required. If you prefer to activate the environment instead, run:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, either keep using the explicit `.venv\Scripts\python.exe` commands above or allow scripts for the current PowerShell process only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 4. Install and enable the Packet Tracer extension

The Python package installs the MCP server; the Packet Tracer extension is a separate component.

1. Download the MCP Control Center `.pts` extension from the [Packet Tracer MCP releases](https://github.com/Mats2208/MCP-Packet-Tracer/releases). Use the extension version documented as compatible with the pinned `packet-tracer-mcp==0.10.2` server; see [`docs/MCP_SETUP.md`](docs/MCP_SETUP.md).
2. Fully exit Packet Tracer before adding a new script module.
3. Start Packet Tracer and open **Extensions → Scripting → Configure PT Script Modules → Add**.
4. Select the downloaded `.pts` file and confirm.
5. Restart Packet Tracer if prompted, accept/enable the detected module, then open **Extensions → MCP BUILDER**.
6. Confirm that the MCP Control Center reports a connected bridge.

The bridge is a separate process from the Python HTTP MCP server. A listening port alone does not prove that the Packet Tracer extension is connected.

### 5. Start the MCP server (PowerShell window 1)

From the project directory:

```powershell
.\.venv\Scripts\python.exe -u -m packet_tracer_mcp
```

Keep this PowerShell window open. The server should expose the default HTTP endpoint:

```text
http://127.0.0.1:39400/mcp
```

If port `39400` is already occupied by a compatible MCP server, do not start a second copy. Check which process owns the port and use the existing server only if it is the expected Packet Tracer MCP instance.

### 6. Start the NetState interface (PowerShell window 2)

Open a second PowerShell window, change to the same project directory, and run:

```powershell
$env:NETSTATE_MCP_ENDPOINT = "http://127.0.0.1:39400/mcp"
$env:NETSTATE_PORT = "8501"
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

Open **http://127.0.0.1:8501** in your browser.

In Packet Tracer, keep **Extensions → MCP BUILDER** open and connected. In NetState, click **Connect & inspect MCP**. Confirm topology discovery returns the devices and links from the open Packet Tracer project before attempting configuration or drift simulation.

### 7. Stop the Windows processes

Press **Ctrl+C** in the Streamlit PowerShell window, then press **Ctrl+C** in the MCP server PowerShell window. Packet Tracer itself can remain open.

### Windows troubleshooting

Check whether the local services are listening:

```powershell
Test-NetConnection 127.0.0.1 -Port 39400
Test-NetConnection 127.0.0.1 -Port 54321
```

- If Python is not found, reopen the terminal after installing Python or use the Python Launcher (`py -3.11`).
- If `dot` is not found, Graphviz is not on `PATH`; reinstall Graphviz or add its `bin` directory to `PATH`, then reopen PowerShell.
- If the MCP server starts but discovery is empty, confirm Packet Tracer is open, MCP BUILDER is enabled, and the bridge reports connected.
- If port `39400` is occupied, identify the process before stopping it. Do not kill an unrelated service.
- If a command is rejected by the simulated IOS, inspect the exact CLI error. Packet Tracer support varies by device model and simulated IOS version; do not rerun a large configuration transaction blindly.

For extension compatibility and bridge diagnostics, see [`docs/MCP_SETUP.md`](docs/MCP_SETUP.md).

## Start and connect (Ubuntu/Linux)

```bash
./start_netstate.sh
```

The launcher starts the MCP server if port `39400` is not already in use, attempts to launch Packet Tracer, and starts the Streamlit interface (default `http://127.0.0.1:8501`). A different port can be selected explicitly:

```bash
NETSTATE_PORT=8507 ./start_netstate.sh
```

In Packet Tracer, open **Extensions → MCP BUILDER** and confirm that the bridge is connected. In NetState, click **Connect & inspect MCP**. A reachable HTTP endpoint alone does not prove the Packet Tracer bridge is connected.

Stop NetState-managed processes with:

```bash
./stop_netstate.sh
```

Packet Tracer itself is intentionally left open.

## First-run workflow

1. Start Packet Tracer and confirm the MCP BUILDER bridge is connected.
2. Start NetState and click **Connect & inspect MCP**.
3. Open **Topology discovery** and discover the live devices, interfaces and links. Use automatic topology planning only if the required MCP tools are available and you have reviewed the plan.
4. Open **Intent, mapping & configure**. Map the logical roles in `config/intent.example.yaml` to the actual discovered devices and interfaces. Review the generated command plan before any configuration change.
5. Open **Drift & reconciliation** and save the mapped intent as the desired state.
6. Run **Analyze live configuration drift**. Confirm that the supported ACL-attachment control is compliant before introducing a change.
7. Save a separate copy of your `.pkt` lab. Open **Drift simulation**, select the intended guest ACL attachment, review the preconditions, and explicitly approve the controlled change.
8. Return to **Drift & reconciliation**. Analyze again, inspect the detected difference, review the one-purpose remediation command, and approve it.
9. Confirm that the new running-config read-back reports `VERIFIED`. Repeat appropriate connectivity tests and inspect ACL counters to corroborate the policy behaviour.

For the exact ACL demonstration, see [`docs/DRIFT_RECONCILIATION.md`](docs/DRIFT_RECONCILIATION.md) and [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md).

## Testing

Ubuntu/Linux:

```bash
source .venv/bin/activate
python -m compileall -q app.py src
python -m pytest -q
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py src
.\.venv\Scripts\python.exe -m pytest -q
```

The automated suite tests parsing, intent validation, topology mapping, MCP response handling, configuration compilation, drift analysis, controlled simulation, remediation planning and read-back logic. Unit tests do not replace a live acceptance test against the exact Packet Tracer model, MCP server and extension installed on the target machine.

## Project layout

```text
NetState-Reconciler/
├── app.py
├── config/
│   ├── intent.example.yaml
│   └── intent.attack-demo-baseline.yaml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEMO_RUNBOOK.md
│   ├── DRIFT_RECONCILIATION.md
│   ├── MCP_SETUP.md
│   ├── SAFETY_AND_LIMITATIONS.md
│   └── WINDOWS_SETUP.md
├── src/netstate_reconciler/
│   ├── binding.py
│   ├── compiler.py
│   ├── config_drift.py
│   ├── deployment.py
│   ├── drift.py
│   ├── engine.py
│   ├── intent.py
│   ├── mcp_client.py
│   ├── models.py
│   ├── reconcile.py
│   ├── security.py
│   └── topology.py
├── tests/
├── tools/
├── install.sh
├── start_netstate.sh
└── stop_netstate.sh
```

## Runtime data and secrets

Runtime state, mappings, checkpoints, snapshots and reports are stored locally under `.netstate/`; logs are stored under `logs/`. These directories are excluded from Git because checkpoints and reports can contain sensitive device configuration. `.env` is also excluded. Do not commit real passwords, tokens, private keys, Packet Tracer project files containing sensitive lab information, or raw configuration captures. Use disposable credentials in classroom labs.

The example YAML files contain demonstration addressing and logical device names, not credentials. Copy and adapt them for your topology; device names and interfaces must be mapped from live discovery.

## Contributing

Issues and pull requests are welcome. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing parser, compiler, reconciliation or transaction behaviour. Any new automatic remediation control should include parser fixtures, positive and negative drift tests, refusal tests for incomplete evidence, and post-change read-back tests.

## License

MIT. See [`LICENSE`](LICENSE).

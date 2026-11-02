#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.11+ is required. Install python3, python3-venv and python3-pip first." >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip wheel
python -m pip install -e '.[dev]'
mkdir -p .netstate/checkpoints .netstate/reports .netstate/snapshots logs
chmod 700 .netstate .netstate/checkpoints .netstate/reports .netstate/snapshots
cat <<'MSG'

NetState Reconciler installed.

Next:
  ./start_netstate.sh

The installer pins packet-tracer-mcp==0.10.2. Install the matching V6
MCP Control Center .pts extension in Cisco Packet Tracer before live use.
See docs/MCP_SETUP.md.
MSG

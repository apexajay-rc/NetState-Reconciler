#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "Environment not installed. Run ./install.sh first." >&2
  exit 1
fi
source .venv/bin/activate

STATE="$ROOT/.netstate"
LOGS="$ROOT/logs"
PIDS="$STATE/pids"
PORT_FILE="$STATE/app_port"
mkdir -p "$STATE" "$LOGS"
chmod 700 "$STATE"

port_listening() {
  python - "$1" <<'PORTCHECK'
import socket, sys
sock = socket.socket()
sock.settimeout(0.35)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
else:
    raise SystemExit(0)
finally:
    sock.close()
PORTCHECK
}

process_matches_root() {
  local service="$1" pid="$2" cmd cwd
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [[ "$cwd" == "$ROOT" ]] || return 1
  case "$service:$cmd" in
    mcp:*packet_tracer_mcp*) return 0 ;;
    streamlit:*streamlit*run*app.py*) return 0 ;;
    *) return 1 ;;
  esac
}

TMP_PIDS="$PIDS.tmp"
: >"$TMP_PIDS"
if [[ -f "$PIDS" ]]; then
  while IFS=: read -r service pid; do
    [[ "$service" =~ ^(mcp|streamlit)$ && "$pid" =~ ^[0-9]+$ ]] || continue
    if kill -0 "$pid" 2>/dev/null && process_matches_root "$service" "$pid"; then
      printf '%s:%s\n' "$service" "$pid" >>"$TMP_PIDS"
    fi
  done <"$PIDS"
fi
mv "$TMP_PIDS" "$PIDS"

MCP_PORT="${NETSTATE_MCP_PORT:-39400}"
if [[ -n "${NETSTATE_PORT:-}" ]]; then
  APP_PORT="$NETSTATE_PORT"
elif [[ -s "$PORT_FILE" ]]; then
  APP_PORT="$(cat "$PORT_FILE")"
else
  APP_PORT="8501"
fi
ENDPOINT="${NETSTATE_MCP_ENDPOINT:-http://127.0.0.1:${MCP_PORT}/mcp}"

launch_packet_tracer() {
  if [[ "${NETSTATE_SKIP_PACKET_TRACER:-0}" == "1" ]]; then
    echo "Packet Tracer auto-launch disabled (NETSTATE_SKIP_PACKET_TRACER=1)."
    return
  fi
  if pgrep -f '[p]ackettracer' >/dev/null 2>&1 || pgrep -f '[P]acket Tracer' >/dev/null 2>&1; then
    echo "Cisco Packet Tracer appears to be running already."
    return
  fi
  if command -v packettracer >/dev/null 2>&1; then
    nohup packettracer >"$LOGS/packet-tracer.log" 2>&1 &
    echo "Launching Cisco Packet Tracer..."
    return
  fi
  if [[ -x /opt/pt/packettracer ]]; then
    nohup /opt/pt/packettracer >"$LOGS/packet-tracer.log" 2>&1 &
    echo "Launching Cisco Packet Tracer from /opt/pt..."
    return
  fi
  local desktop_file
  desktop_file="$(grep -il 'Cisco Packet Tracer' "$HOME"/.local/share/applications/*.desktop /usr/share/applications/*.desktop 2>/dev/null | head -n1 || true)"
  if [[ -n "$desktop_file" ]] && command -v gtk-launch >/dev/null 2>&1; then
    local desktop_id
    desktop_id="$(basename "$desktop_file" .desktop)"
    nohup gtk-launch "$desktop_id" >"$LOGS/packet-tracer.log" 2>&1 &
    echo "Launching Cisco Packet Tracer from desktop entry..."
    return
  fi
  echo "Could not locate Packet Tracer executable. Open it manually; NetState will continue."
}

if port_listening "$MCP_PORT"; then
  echo "MCP HTTP server already listening on port $MCP_PORT; leaving it untouched."
else
  echo "Starting Packet Tracer MCP server on port $MCP_PORT..."
  nohup python -u -m packet_tracer_mcp >"$LOGS/packet-tracer-mcp.log" 2>&1 &
  MCP_PID=$!
  printf 'mcp:%s\n' "$MCP_PID" >>"$PIDS"
  for _ in $(seq 1 40); do
    if port_listening "$MCP_PORT"; then break; fi
    if ! kill -0 "$MCP_PID" 2>/dev/null; then
      echo "MCP server exited during startup. Tail of logs:" >&2
      tail -n 60 "$LOGS/packet-tracer-mcp.log" >&2 || true
      exit 1
    fi
    sleep 0.5
  done
  if ! port_listening "$MCP_PORT"; then
    echo "MCP server did not open port $MCP_PORT. See $LOGS/packet-tracer-mcp.log" >&2
    exit 1
  fi
fi

launch_packet_tracer

EXPLICIT_PORT="${NETSTATE_PORT+x}"
if port_listening "$APP_PORT"; then
  SAME_PROJECT_PID=""
  while IFS=: read -r service pid; do
    if [[ "$service" == "streamlit" ]] && process_matches_root streamlit "$pid"; then
      SAME_PROJECT_PID="$pid"
      break
    fi
  done <"$PIDS"
  if [[ -n "$SAME_PROJECT_PID" ]]; then
    echo "NetState from this project is already running on port $APP_PORT (PID $SAME_PROJECT_PID). Reusing it."
  elif [[ -n "$EXPLICIT_PORT" ]]; then
    echo "Port $APP_PORT is occupied by another process. Stop it or choose another port with NETSTATE_PORT=8502." >&2
    exit 1
  else
    BASE_PORT="$APP_PORT"
    FOUND=""
    for candidate in $(seq $((BASE_PORT + 1)) $((BASE_PORT + 20))); do
      if ! port_listening "$candidate"; then FOUND="$candidate"; break; fi
    done
    if [[ -z "$FOUND" ]]; then
      echo "No free Streamlit port found between $((BASE_PORT + 1)) and $((BASE_PORT + 20)). Set NETSTATE_PORT explicitly." >&2
      exit 1
    fi
    echo "Port $APP_PORT is occupied by another application; starting this project on port $FOUND instead."
    APP_PORT="$FOUND"
  fi
fi

if ! port_listening "$APP_PORT"; then
  echo "Starting NetState Reconciler at http://127.0.0.1:${APP_PORT} ..."
  export NETSTATE_PORT="$APP_PORT"
  nohup python -m streamlit run app.py --server.address 127.0.0.1 --server.port "$APP_PORT" --server.headless true >"$LOGS/netstate.log" 2>&1 &
  APP_PID=$!
  printf 'streamlit:%s\n' "$APP_PID" >>"$PIDS"
  printf '%s\n' "$APP_PORT" >"$PORT_FILE"
  for _ in $(seq 1 20); do
    if port_listening "$APP_PORT"; then break; fi
    if ! kill -0 "$APP_PID" 2>/dev/null; then
      echo "NetState GUI failed to start. See $LOGS/netstate.log" >&2
      tail -n 60 "$LOGS/netstate.log" >&2 || true
      exit 1
    fi
    sleep 0.5
  done
  if ! port_listening "$APP_PORT"; then
    echo "NetState did not open port $APP_PORT. See $LOGS/netstate.log" >&2
    exit 1
  fi
fi

export NETSTATE_MCP_ENDPOINT="$ENDPOINT"
export NETSTATE_PORT="$APP_PORT"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:${APP_PORT}" >/dev/null 2>&1 || true
fi
cat <<MSG

NetState Reconciler is running.
GUI:        http://127.0.0.1:${APP_PORT}
MCP:        ${ENDPOINT}
MCP bridge: http://127.0.0.1:54321 (managed by Packet Tracer MCP)
Project:    ${ROOT}
Logs:       ${LOGS}
Stop NetState-managed processes with ./stop_netstate.sh

In Cisco Packet Tracer, open Extensions → MCP BUILDER and confirm
that the bridge status is connected before using Discover Network.
MSG

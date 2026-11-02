#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PIDS="$ROOT/.netstate/pids"
PORT_FILE="$ROOT/.netstate/app_port"
if [[ ! -f "$PIDS" ]]; then
  echo "No NetState-managed PID file found. No processes were stopped."
  exit 0
fi
stopped=0
while IFS=: read -r service pid; do
  [[ "$pid" =~ ^[0-9]+$ ]] || continue
  [[ "$service" == "mcp" || "$service" == "streamlit" ]] || continue
  [[ -r "/proc/$pid/cmdline" ]] || continue
  cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [[ "$cwd" == "$ROOT" ]] || { echo "Skipped PID $pid: working directory does not match this project."; continue; }
  case "$service:$cmdline" in
    mcp:*packet_tracer_mcp*|streamlit:*streamlit*run*app.py*)
      kill "$pid" 2>/dev/null || true
      echo "Stopped NetState-managed $service process ($pid)"
      stopped=$((stopped + 1))
      ;;
    *)
      echo "Skipped PID $pid: process no longer matches recorded service '$service'."
      ;;
  esac
done < <(tac "$PIDS")
rm -f "$PIDS" "$PORT_FILE"
if [[ "$stopped" -eq 0 ]]; then
  echo "No matching NetState-managed processes were running."
else
  echo "Stopped $stopped NetState-managed process(es). Cisco Packet Tracer was left open."
fi

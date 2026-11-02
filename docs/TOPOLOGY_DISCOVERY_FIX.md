# Topology discovery and launcher correction

This correction keeps the canonical NetState Reconciler project version at 1.0.0.
It does not create a separate product version.

## What changed

- The topology engine preserves the raw responses and parsed record counts for both
  `pt_export_topology` and `pt_query_topology`, including on failure.
- The Topology discovery UI displays that diagnostic directly after a failed attempt.
- The sidebar and Diagnostics page display the application build, process ID and port.
- The launcher no longer silently reuses an unrelated service on port 8501. If the
  default port is occupied, it chooses the next free port (normally 8502) and opens
  the correct project there.
- The launcher retains and stops only processes that match this project directory.
- Regression coverage includes the exact MCP 0.10.2 topology text returned in the
  user's diagnostic output.

## Why this matters

The prior terminal output showed that port 8501 was already occupied and that the
launcher therefore did not start a new Streamlit process. The browser could remain
on an older application instance. This launcher makes that situation explicit and
starts the current project on a free port instead.

The bundled read-only diagnostic command also now calls the same topology parser
used by the GUI, so it reports parsed device/link counts rather than using a
separate, potentially divergent extraction routine. Run it with:

```bash
.venv/bin/python tools/diagnose_mcp.py
```

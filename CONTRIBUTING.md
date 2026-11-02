# Contributing

Thanks for helping improve NetState Reconciler.

## Development setup

- Use Python 3.11 or newer.
- Install system prerequisites listed in `README.md`.
- Run `./install.sh` to create the local virtual environment.
- Run `python -m compileall -q app.py src` and `python -m pytest -q` before opening a pull request.

## Change expectations

- Keep the core parser, desired-state comparison, remediation planner and MCP adapter independently testable.
- Do not infer compliance when device output is missing, ambiguous or incomplete. Return an explicit unobserved/unsupported state.
- Never treat command submission as proof of a successful configuration change. Add fresh read-back verification.
- Automatic remediation must be minimal, preconditioned, reviewable and explicitly approved.
- Do not add arbitrary raw CLI execution from YAML or free-form user input.
- Add tests for successful parsing, malformed output, unsupported syntax, no-drift, drift, false-positive boundaries, execution failure and verification failure as applicable.
- Preserve local runtime files and user data; do not commit `.netstate/`, `logs/`, `.env`, virtual environments, generated caches or raw device checkpoints.
- Keep Packet Tracer integration limitations explicit. Unit tests do not establish compatibility with every simulated IOS model.

## Pull requests

1. Create a topic branch from `main`.
2. Make a focused change with tests and documentation.
3. Run the test commands above.
4. Describe the supported behaviour, limitations and any live Packet Tracer test performed.
5. Do not include passwords, access tokens, private keys, personal lab captures or unredacted running configurations.

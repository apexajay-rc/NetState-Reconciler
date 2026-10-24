# NetState Reconciler

**Automated Network Configuration Drift Detection and Remediation**

NetState Reconciler is a Python-based desired-state auditor for a bounded, documented subset of Cisco IOS running configurations. It compares an approved YAML specification with actual router configuration, reports drift with severity, and creates a reviewable remediation plan. It supports saved configuration exports (useful with Cisco Packet Tracer) and an optional SSH adapter for IOS devices/labs that support Netmiko.

> **Scope and safety:** This is a portfolio/learning project, not a production NMS. Cisco Packet Tracer device CLI capabilities differ from physical IOS devices. The file collector is the supported Packet Tracer workflow; do not assume that Netmiko SSH access works with simulated Packet Tracer routers. The current planner does not auto-apply ACL or OSPF changes, interface IP changes, interface administrative-state changes, or ACL-binding changes. Those changes are deliberately marked for manual review because they can change reachability or interrupt traffic.

## Features

- YAML desired-state validation with actionable errors.
- Parser for hostname, interface IPv4 address/mask, admin state, descriptions, inbound/outbound ACL bindings, numbered/named ACL entries, and OSPF router ID/network statements.
- Ordered ACL comparison; entry order is treated as meaningful.
- Drift findings with paths, desired/actual values, severity, and explanations.
- Strict resource mode for flagging undeclared interfaces, ACLs, and OSPF processes.
- Remediation planning with command suggestions and explicit manual-review boundaries.
- Optional Netmiko SSH collection and conservative execution of only planner-approved actions.
- Post-remediation audit, JSON report output, and pytest tests.

## Quick start (Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
cd ~/projects
# If you cloned this repository, cd into the cloned directory instead.
cd netstate-reconciler
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

If the project is in another directory, use that path rather than `~/projects/netstate-reconciler`.

Validate the example desired state:

```bash
netstate validate --desired configs/router1.yaml
```

Audit the supplied baseline fixture (expected: `COMPLIANT`):

```bash
netstate audit \
  --desired configs/router1.yaml \
  --source tests/fixtures/router1_running.txt
```

Audit a fixture containing intentional drift (expected: `NON-COMPLIANT`, exit status 1):

```bash
netstate audit \
  --desired configs/router1.yaml \
  --source tests/fixtures/router1_with_drift.txt \
  --json-output reports/drift-report.json
```

Print a remediation plan without executing commands:

```bash
netstate plan \
  --desired configs/router1.yaml \
  --source tests/fixtures/router1_with_drift.txt \
  --json-output reports/remediation-plan.json
```

Run tests:

```bash
pytest
```

## Cisco Packet Tracer workflow

1. Build a small topology in Packet Tracer and configure your router.
2. On the router CLI, run `show running-config`.
3. Copy the complete configuration output (or at least the supported relevant sections) into a local UTF-8 text file, for example `live_configs/router1_running.txt`.
4. Create/edit a YAML specification under `configs/` to describe the approved state.
5. Run `netstate audit --desired configs/router1.yaml --source live_configs/router1_running.txt`.
6. Introduce one controlled drift in Packet Tracer, export the configuration again, and rerun the audit to demonstrate detection.
7. Review the plan output. The file mode is intentionally read-only; it cannot push corrections to Packet Tracer.

The included `tests/fixtures/` files are synthetic sample outputs, not captured from a physical router. Replace them with your own Packet Tracer output for your project demonstration.

## Optional SSH workflow

The SSH collector/executor is for Cisco IOS devices or virtual lab devices that expose a supported SSH CLI. It is not guaranteed to work with Packet Tracer.

Install the optional dependency:

```bash
python -m pip install -e '.[ssh]'
```

Set credentials through the environment (or supply the username and enter the password at the prompt):

```bash
export NETSTATE_USERNAME='your-username'
# Optional: store these in a private shell/session only; do not commit secrets.
export NETSTATE_PASSWORD='your-password'
# Only if enable mode is required:
export NETSTATE_ENABLE_SECRET='your-enable-secret'
```

Audit a device:

```bash
netstate audit --desired configs/router1.yaml --host 192.0.2.10
```

Generate a plan against a device:

```bash
netstate plan --desired configs/router1.yaml --host 192.0.2.10
```

The executor requires `--confirm`, applies only actions explicitly marked auto-applicable by the planner, and performs a follow-up audit. Review the plan first and use an isolated lab. Do not test remediation on a production router. The current conservative planner does **not** automatically apply ACL/OSPF changes, interface addressing, interface shutdown/no-shutdown, or ACL-binding changes.

## Desired-state YAML

`configs/router1.yaml` is the complete example. The schema supports:

```yaml
hostname: Router1
strict: false
interfaces:
  GigabitEthernet0/0:
    description: Uplink to LAN
    ipv4_address: 192.168.1.1
    ipv4_mask: 255.255.255.0
    admin_state: up
    access_groups:
      in: "100"
acls:
  "100":
    type: extended
    entries:
      - permit ip 10.0.0.0 0.255.255.255 any
      - deny ip any any log
ospf:
  "1":
    router_id: 1.1.1.1
    networks:
      - network: 192.168.1.0
        wildcard: 0.0.0.255
        area: "0"
```

Only declared fields are managed. Fields omitted from a desired-state file are not checked, unless `strict: true` is enabled for resource-level checks of undeclared interfaces, ACLs, and OSPF processes. ACL entry order must match because IOS access lists are ordered rules. Avoid declaring only some ACL lines if the intent is to validate the entire ACL.

## CLI reference

```text
netstate validate --desired PATH
netstate audit --desired PATH (--source FILE | --host HOST) [--json-output FILE]
netstate plan  --desired PATH (--source FILE | --host HOST) [--json-output FILE]
netstate apply --desired PATH --host HOST --confirm [--username USER] [--json-output FILE]
```

Exit codes: `0` means the audit is compliant (or validation succeeded); `1` means drift remains; `2` means invalid input or an operational error. A drift exit status of 1 is expected during demonstrations where drift is intentionally introduced.

## Current parser coverage and limitations

This version models a defined subset of IOS configuration, not every IOS command or platform. It does not fully model secondary IPv4 addresses, DHCP addressing, IPv6, NAT, BGP, route maps, VRFs, VLAN trunking, AAA, all ACL syntax variants, or operational state such as physical link-up. Secondary/DHCP interface addressing produces a parser warning. An audit with parser warnings requires human review; a clean result is only as complete as the parser's supported configuration model.

The current desired-state comparison treats lists as ordered and dictionaries as a set of managed keys. It does not prove full network reachability or formally verify that an ACL's effective policy meets a business security intent. `strict: true` catches extra resources but does not treat every unmodeled command as drift.

## Repository layout

```text
src/netstate/
  cli.py                         CLI and workflow orchestration
  configuration.py               YAML loading and validation
  models.py                       Drift/action/report models
  collectors/file.py              Saved config input
  collectors/netmiko_collector.py Optional SSH collection
  parsers/ios.py                  Cisco IOS running-config parser
  reconciler/diff.py              Desired/actual comparison
  remediation/planner.py          Proposed commands and risk boundaries
  remediation/executor.py         Confirmed execution of safe actions
configs/router1.yaml               Example desired state
tests/fixtures/                   Synthetic Cisco IOS configuration samples
tests/                             Unit tests
```

## Suggested next engineering improvements

1. Add broader IOS syntax coverage with parser fixtures from multiple IOS versions.
2. Replace raw interface/ACL parsing with a structured AST and explicit unsupported-command coverage.
3. Add stateful integration tests using a virtual IOS-compatible lab.
4. Build a remediation transaction model with checkpoints, rollback, and device-specific capability policies.
5. Add topology-aware validation and policy invariants, then measure false positives and false negatives on a labelled test corpus.

## License

MIT. See `LICENSE`.
# NetState-Reconciler

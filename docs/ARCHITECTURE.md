# Architecture

## Architectural style

NetState is a local modular monolith. The Streamlit GUI, desired-state model, topology binding, configuration compiler, MCP adapter, drift engine, reconciliation planner and evidence store run in one Python application while remaining separate modules for testing.

## Runtime flow

```text
Streamlit UI
    |
    v
Workflow controller
    |
    +--> MCP tool catalog and Packet Tracer bridge
    |
    +--> Topology discovery --> device/interface/link inventory
    |
    +--> YAML intent --> schema validation --> logical-to-physical binding
    |
    +--> Configuration preview --> approval --> checkpointed execution
    |
    +--> Desired-state baseline
    |        |
    |        v
    |    Live running-config collection
    |        |
    |        v
    |    Semantic comparison (1.2.0: named router ACL attachments)
    |        |
    |        v
    |    Drift findings --> minimal remediation plan --> approval
    |                                             |
    |                                             v
    |                                    Apply and read back
    |                                             |
    |                                             v
    |                                    Verification evidence
    |
    +--> Reachability, health and security-posture diagnostics
    |
    +--> Local evidence store
```

## Desired state and topology binding

The user declares target state in YAML. `binding.py` maps logical router, switch and host roles to discovered Packet Tracer devices, and maps logical interface identifiers to actual discovered ports. Cisco interface aliases are normalized for comparison while the discovered spelling is retained for CLI output. Ambiguous mappings require operator selection.

## Configuration compiler and execution

The compiler converts supported structured intent fields into IOS command plans. The UI exposes the plan and requires explicit approval. Checkpoints are captured where supported. Commands execute sequentially and the application stops at a recognized failure. The workflow records partial progress; it does not claim atomic multi-device rollback.

## Reconciliation engine (1.2.0)

The first semantic control parses interface stanzas, named IPv4 ACL definitions and `ip access-group` attachments from live router configuration. It compares mapped desired ACL attachments with the observed state. A narrow repair is generated only when the interface and desired ACL definition are present and the observed configuration is complete enough to support the operation. After approval, the engine applies the attachment command and retrieves running configuration again. `VERIFIED` requires the read-back to match the targeted desired state.

Other configuration families are outside the 1.2.0 semantic reconciliation scope. They must not be reported as semantically compliant merely because no supported ACL drift was found.

## Evidence and local state

The application stores topology snapshots, redacted running-config snapshots, device/interface mappings, checkpoints and execution reports under `.netstate/`. Logs are stored under `logs/`. These runtime directories are private local state and must not be committed to Git.

## Trust boundaries and limits

- MCP endpoint defaults to localhost; bridge connectivity is checked separately.
- Live configuration changes require explicit approval.
- The compiler accepts structured intent rather than arbitrary CLI blocks.
- Packet Tracer command support varies by simulated model and IOS version.
- Command submission is not proof of configuration correctness; read-back is required.
- The project is an educational Packet Tracer demonstrator, not a complete multi-vendor network configuration management platform.

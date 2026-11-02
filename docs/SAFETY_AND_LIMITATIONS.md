# Safety model and implementation limits

## Live change safeguards

- Discovery and topology mapping are required before device configuration.
- Generated plans are shown before execution and require explicit operator approval.
- Checkpoints are requested where the MCP server supports them.
- A checkpoint failure blocks execution by default unless the operator explicitly acknowledges proceeding without one.
- Execution stops at the first recognized command failure and records partial progress.
- A submitted command is never described as verified solely because the CLI tool returned.

## Drift simulation safeguards

The 1.2.0 drift simulator targets one named router IPv4 ACL attachment. Before changing a device, it reads the live running configuration and verifies the intended ACL definition and attachment. It requests a checkpoint where supported and requires explicit approval. It must refuse the operation when the preconditions are not met or the relevant configuration cannot be observed safely.

## Rollback boundary

The application saves local checkpoints and stops on execution failure. It does not claim automatic atomic rollback across multiple devices. A startup-config checkpoint is not necessarily equivalent to restoring the prior running configuration. Inspect the device and use a verified, device-specific recovery procedure after a partial failure.

## Reconciliation scope

Semantic automatic drift detection and repair in 1.2.0 cover named router IPv4 ACL attachments only. VLANs, trunks, DHCP, OSPF, static routes, port security, host addressing and arbitrary IOS configuration are not covered by this semantic repair engine. Running-config text snapshots can provide supporting change evidence, but textual differences can be caused by ordering or formatting and are not equivalent to semantic drift.

When a parser cannot recognize a command or the MCP response is incomplete, the application should report unsupported or unobserved state rather than infer compliance.

## Security posture and reachability

Security-posture findings are separate from configuration drift unless the relevant requirement is included in the desired intent. ICMP reachability shows whether the tested source-to-target ICMP path responded; packet loss alone does not prove that an ACL caused the loss or that every application service is blocked.

## Platform limitations

Cisco IOS command support varies by Packet Tracer device model and simulated IOS release. SSH RSA key generation may need to be completed interactively on the device. The MCP tool catalog is discovered at runtime, and not every documented MCP action is guaranteed to be present in every extension build. The live integration must be tested on the target Packet Tracer/MCP installation.

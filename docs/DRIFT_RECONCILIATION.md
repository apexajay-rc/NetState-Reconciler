# Drift detection and reconciliation (1.2.0)

## Purpose

NetState Reconciler is centered on comparing the mapped desired network intent with the live Packet Tracer configuration, explaining supported deviations, generating a narrow correction, and verifying the result by read-back.

## First supported semantic control

Version 1.2.0 implements semantic detection and controlled reconciliation for **named router ACL attachments** declared in the mapped `NetworkIntent`:

- The parser extracts interface stanzas, named ACL definitions, and `ip access-group <name> in|out` attachments.
- Interface names are normalized for comparison (`Gi0/1.20` and `GigabitEthernet0/1.20` compare as the same interface).
- Missing or wrong ACL attachments are reported with device, interface, expected state, observed state, and severity.
- Automatic repair is permitted only if the interface is present and the desired named ACL definition already exists in the captured configuration.
- Repair applies only `ip access-group <name> <direction>` on the affected interface, then captures the running configuration again.
- `VERIFIED` is returned only when read-back confirms that all targeted ACL attachments match the desired intent.

Missing ACL definitions, missing interface stanzas, or incomplete configuration collection are not automatically repaired. They are reported for manual review or as unobserved state. This version does **not** claim complete semantic verification of all IOS configuration families. VLAN, DHCP, OSPF, static-route, port-security, and host settings are outside the automatic reconciler's current scope.

## Controlled demonstration

1. Connect to MCP and discover the live topology.
2. Open **Intent, mapping & configure** and complete device/interface mappings.
3. Open **Drift & reconciliation** and save the mapped intent as the desired state.
4. Confirm the desired guest ACL is present and attached by running **Analyze live configuration drift**. The ACL-attachment scope should report compliant.
5. Save a separate `.pkt` project copy.
6. Open **Drift simulation**, select the intended ACL attachment, approve the operation, and inject the controlled drift. The simulator first reads the live config, verifies the intended ACL is present and attached, and attempts a device checkpoint. A missing checkpoint requires explicit acknowledgement.
7. Return to **Drift & reconciliation** and analyze again. Expect `MISSING_ACL_ATTACHMENT`.
8. Review the minimal repair command. Approve it and apply. NetState checkpoints the affected device where supported, applies only the ACL attachment command, captures the running config again, and reports `VERIFIED` only after read-back.
9. Optionally use the ICMP probe to demonstrate the traffic effect before and after the change. ICMP loss by itself is not proof that an ACL caused the loss; the configuration comparison establishes the drift.

## Transaction semantics

- `SUBMITTED` means the CLI tool returned without a recognized error; it is not proof of a correct configuration.
- `VERIFIED` means the live read-back matched the targeted desired state.
- `APPLIED_UNVERIFIED`, `PARTIAL`, and `PARTIAL_FAILURE` are non-success states and require inspection.
- Checkpoint files are local evidence. The application does not claim atomic multi-device rollback.
- The controlled drift simulator changes exactly one ACL attachment and refuses to overwrite an unexpected pre-existing state.

## RSA/SSH command compatibility

Packet Tracer IOS command parsers may reject inline `crypto key generate rsa modulus 1024` when commands are sent as a batch. The compiler no longer sends that inline form. It configures the non-interactive SSH prerequisites and VTY settings; RSA key generation must be completed interactively on the router (`crypto key generate rsa`, then answer the modulus prompt) before SSH access is expected to work.

## Validation

The automated suite covers ACL parsing, expected-vs-observed comparison, explicit simulation approval, checkpoint handling, minimum remediation, and post-change read-back. Passing unit tests does not prove compatibility with every Packet Tracer IOS model or MCP bridge. The first run against a live Packet Tracer lab remains an integration test.

# Architecture and design decisions

## Data flow

```text
Approved YAML
     |
     v
Schema validation -------------------------+
     |                                     |
     v                                     |
Desired state                              |
                                           v
Saved config / SSH collector -> IOS parser -> Actual state
                                           |
                                           v
                                  Desired/actual diff
                                           |
                            +--------------+--------------+
                            |                             |
                            v                             v
                       Audit report                 Remediation planner
                                                          |
                                            +-------------+-------------+
                                            |                           |
                                            v                           v
                                      Safe command set             Manual review
                                            |
                                            v
                                 Explicitly confirmed executor
                                            |
                                            v
                                  Re-collect and re-audit
```

## Main invariants

- Audit is read-only.
- Plan is read-only and emits recommendations only.
- `apply` requires `--confirm` and only executes planner actions marked `auto_applicable`.
- ACL and OSPF changes are never auto-applied in this version.
- A follow-up audit is required; a successful CLI response alone is not proof of compliance.
- Only declared fields are managed; the YAML's `strict` option also detects unexpected interface, ACL, and OSPF resource objects.
- ACL entries are compared in order.

## Why file input exists

Packet Tracer is a useful topology simulator, but simulated device services are not equivalent to physical Cisco IOS. File input decouples the parser and reconciliation logic from the collection transport so they can be tested using exported `show running-config` text. The SSH adapter is optional and targets a device/lab that exposes a compatible SSH CLI.

## Remediation risk model

The planner treats hostname/description-only commands as eligible for application after explicit confirmation. Interface IP changes, interface shutdown/no-shutdown, ACL binding changes, ACL edits, and OSPF drift require manual review. These operations can affect reachability, rule ordering, or route propagation. Planner output is not a guarantee that commands will be accepted by every IOS version; always test in an isolated lab.


## Version 0.2.0 safety behavior

The parser emits warnings for unknown commands within interface and OSPF contexts and for selected global configuration features that materially affect security or routing but are not modeled by the desired-state schema. CLI audit reports with parser warnings are marked incomplete rather than compliant. The global-command checks are intentionally targeted, not exhaustive; absence of a warning is not proof that every IOS feature was audited.

Numbered ACL entries are ordered policy. When an ACL diff is detected, the planner proposes removing the current entries and re-adding the desired list in order. Such actions remain manual-review-only because updating an applied ACL can temporarily alter traffic filtering.

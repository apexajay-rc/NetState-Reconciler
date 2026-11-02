# Changelog

## 1.2.0 — Drift detection and reconciliation

- Made configuration drift reconciliation the primary project workflow.
- Added semantic comparison for named router IPv4 ACL attachments.
- Added controlled simulation of an ACL attachment removal with precondition checks and explicit approval.
- Added minimal ACL reattachment remediation and fresh running-config read-back verification.
- Refused automatic repair when required interface, ACL definition or configuration evidence is missing.
- Removed the Packet Tracer-incompatible inline RSA key-generation command from bulk SSH hardening compilation; RSA generation is an interactive device step.

## 1.1.0 — Topology-aware binding

- Added persistent mappings from logical intent roles to discovered Packet Tracer devices and interfaces.
- Added Cisco interface alias normalization and link-informed interface suggestions.

## 1.0.x — Discovery and deployment workflow

- Added capability-aware topology planning/deployment handling, discovery diagnostics and readable reachability evidence.

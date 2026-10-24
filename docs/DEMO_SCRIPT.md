# Five-minute project demonstration

1. Show the approved state: `configs/router1.yaml`.
2. Run `netstate validate --desired configs/router1.yaml`.
3. Audit the baseline fixture and show `COMPLIANT`:
   `netstate audit --desired configs/router1.yaml --source tests/fixtures/router1_running.txt`
4. Audit the drift fixture and show the IP mismatch plus unexpected ACL entry:
   `netstate audit --desired configs/router1.yaml --source tests/fixtures/router1_with_drift.txt`
5. Generate, but do not apply, a plan:
   `netstate plan --desired configs/router1.yaml --source tests/fixtures/router1_with_drift.txt --json-output reports/plan.json`
6. Explain why ACL changes are marked for review and why a correction must be verified after execution.
7. Show automated tests with `pytest -v`.
8. For the live Packet Tracer demonstration, export/copy a real `show running-config` output to a file, adjust the desired YAML for that topology, and repeat the audit before and after introducing one controlled drift.

The included fixtures are synthetic; be explicit in the presentation when showing them. Do not present synthetic configuration as output captured from a real Packet Tracer session.


## Version 0.2.0 additional regression demonstrations

1. Confirm that an unmodeled security-sensitive global command (for example, a local `username` line) produces a parser warning. The audit must not report full compliance when parser warnings exist.
2. Confirm that unknown interface and OSPF commands produce warnings instead of being silently skipped.
3. Create a numbered ACL fixture whose entries have the same membership but different order. Confirm the audit reports drift and the planner proposes an ordered rebuild that remains manual-review-only.
4. Validate that `255.0.255.0` is rejected as an IPv4 subnet mask and that ACL binding directions other than `in` or `out` are rejected.

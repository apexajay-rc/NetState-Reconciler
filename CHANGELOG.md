# Changelog

## 0.2.0

- Fail-safe warnings for unknown interface and OSPF subcommands and selected security/routing-sensitive global features outside the modeled subset.
- Stronger validation for contiguous IPv4 subnet masks and ACL binding directions.
- Numeric ACL binding values normalized to strings.
- Explicit `null` desired values match absent nullable properties.
- Numbered ACL plans now rebuild entries in desired order when order differs; ACL actions remain manual-review-only.
- Regression suite increased from 13 to 22 tests.

## 0.1.0

- Initial desired-state auditor, Cisco IOS parser, drift detector, remediation planner, optional Netmiko collector, and conservative executor.

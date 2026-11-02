# Topology-aware device and interface binding

## Problem

The sample intent uses logical names such as `R1`, `SW1`, and `PC-EMPLOYEE`, plus illustrative interface identifiers. Packet Tracer inventories commonly use display names such as `Router0`, `Switch0`, or interface abbreviations such as `Gi0/0`. Comparing these strings directly incorrectly reports missing devices and interfaces.

## 1.1.0 workflow

1. Discover the live Packet Tracer devices, interface catalog, and physical links.
2. Open **Intent, mapping & configure** and select the actual device for each logical router, switch, and host role.
3. Review interface suggestions. Exact Cisco aliases are normalized for comparison. An interface description containing a peer hint such as `TRANSIT_TO_R2` can be resolved against a unique discovered link to the mapped R2 device.
4. Manually select any interface for which topology evidence is ambiguous.
5. Save mappings locally. They are project-scoped and reused on subsequent runs.
6. NetState translates device names, router physical interfaces, subinterface parents, ACL attachment interfaces, switch access ports, switch trunks, and host targets.
7. The translated intent is validated against the live inventory. Configuration remains disabled if a required mapping is missing, duplicated, or points to an interface absent from the selected device.

## Important limits

- Device role inference is not automatic: an operator must identify which discovered router/switch/host represents each logical role. Device models filter the selection list when possible.
- Interface suggestions are conservative. A physical link proves which ports are connected, but does not by itself establish the intended VLAN or security role of a port. Ambiguous port-to-role assignments require an operator decision.
- Cisco aliases are canonicalized for comparison only. Generated configuration uses the exact discovered interface spelling.
- Subinterfaces such as `Gi0/0.10` are not expected to appear as physical inventory ports; NetState resolves them through the selected physical parent interface.
- If a topology is rebuilt, renamed, or re-cabled, review and save the mappings again.

## Validation

Run `pytest -q`. The binding tests cover device alias translation, router and switch interface translation, subinterface and ACL parent mapping, Cisco alias normalization, missing mapping detection, and topology-link-based peer suggestions. Live acceptance still requires running the app against the installed Packet Tracer MCP bridge.

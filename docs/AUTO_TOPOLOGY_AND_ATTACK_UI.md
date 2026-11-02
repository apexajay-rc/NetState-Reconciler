# Automatic topology workflow and readable Attack & Defend UI

## What this build changes

- The Topology discovery tab now includes a guided topology planner using `pt_plan_topology` when that tool is exposed by the connected MCP server.
- Builder inputs include router count, PCs per LAN, switches per router, and routing preference. Arguments are mapped against the live MCP tool schema rather than hard-coded to one fixed schema.
- A plan is displayed for review before deployment. A deployment attempt requires a separate explicit confirmation and a recognized build/deploy tool.
- After a build action returns, NetState attempts fresh topology discovery and displays the actual inventory and links.
- Attack & Defend now presents human-readable outcomes, source/destination cards, a plain-language explanation, and expandable technical evidence. Raw JSON payloads are not the primary output in this panel.
- The app supports arbitrary discovered device names in the Attack & Defend source selector and uses discovered IP addresses as target suggestions where available.

## Important boundaries

MCP tool names and schemas vary by Packet Tracer MCP Control Center version. If the server exposes a planner but no compatible deployment tool, the app displays that distinction and does not claim that the network was built. If the deployment tool requires an argument that cannot be mapped safely from its schema, deployment is stopped with an error for inspection in Diagnostics.

Topology discovery identifies physical links and interface identifiers; it does not by itself prove VLAN intent, subnet allocation, DHCP behavior, routing adjacency, or ACL policy. These properties still require generated intent plus post-change read-back and reachability checks. The current implementation should be treated as a capability-aware builder workflow, not unrestricted automatic network design.

## Verification

Run the test suite from the project directory:

```bash
python -m pytest -q
python -m compileall -q app.py src
```

Then on the target Ubuntu machine:

1. Start the MCP server and Packet Tracer MCP BUILDER bridge.
2. Start NetState and click **Connect & inspect MCP**.
3. Confirm `pt_plan_topology` is listed in Diagnostics → MCP Tools.
4. Plan a small lab; inspect the plan response.
5. Deploy only if a recognized deployment tool is present and the correct Packet Tracer workspace is open.
6. Rediscover topology and verify actual devices/links.
7. Run Attack & Defend against a known target; compare the plain-language result with the expandable evidence and Packet Tracer packet trace.


## 1.0.3 deployment correctness update

- MCP `plan_path` arguments receive an absolute path to a persisted `.json` file under `.netstate/plans/`; JSON-content fields such as `plan_json` are serialized according to their declared schema.
- If `pt_validate_plan` is present, NetState validates before deployment and blocks explicit validation errors.
- MCP deployment responses are displayed and checked for errors.
- A deployment is only marked verified after devices and links are read back from Packet Tracer.
- Read-back is retried briefly to allow the Packet Tracer extension to finish applying the topology.


### Packet Tracer MCP 0.10.1+ plan path handling

`pt_validate_plan` and `pt_live_deploy` accept `plan_path`, which must identify an existing `.json` file. NetState persists the extracted plan once and reuses the same absolute path for validation and deployment. The file is retained under `.netstate/plans/` for inspection and troubleshooting.

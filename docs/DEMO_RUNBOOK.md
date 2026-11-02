# Live project demonstration runbook (1.2.0)

## Prepare Packet Tracer

Create or open a lab with:

- R1 and R2 (compatible Cisco routers).
- SW1 and SW2 (compatible Cisco switches).
- An employee PC, guest PC and finance PC.
- R1-to-R2 routed connectivity.
- R1-to-SW1 trunk carrying employee and guest VLANs.
- R2-to-SW2 connectivity for the finance network.

Use topology discovery to identify actual device names, interface labels and links. Do not assume the sample YAML's device names or port numbers match your canvas.

## Start and connect

```bash
./start_netstate.sh
```

Open Packet Tracer → Extensions → MCP BUILDER and confirm the bridge is connected. In NetState, click **Connect & inspect MCP**.

## Discover and establish desired state

1. Discover the live topology.
2. Review devices, interfaces and physical links.
3. Open **Intent, mapping & configure** and map the logical aliases in `config/intent.example.yaml` to discovered devices and ports.
4. Validate the intent and review any generated configuration. Do not apply a full configuration merely to establish a baseline if the lab is already configured.
5. Open **Drift & reconciliation** and save the mapped intent as desired state.
6. Analyze live configuration drift. Confirm the supported ACL attachment control is compliant.

## Controlled ACL drift demonstration

1. Save a separate copy of the `.pkt` file before injecting drift.
2. Open **Drift simulation**.
3. Select the desired guest ACL attachment on R1 (the mapped guest subinterface, ACL name and direction must match the saved intent).
4. Review the precondition report. The simulator must confirm that the ACL definition and expected attachment currently exist.
5. Explicitly approve the single change. The simulator removes only the selected ACL attachment.
6. Open **Drift & reconciliation** and analyze again.
7. Review the reported expected-versus-observed state.
8. Review the minimal remediation command and explicitly approve it.
9. NetState applies the correction, captures a fresh running configuration and reports `VERIFIED` only if read-back confirms the attachment.
10. Repeat employee-to-finance and guest-to-finance reachability probes. Inspect the ACL counter and interface attachment as corroborating evidence.

## Expected ACL scenario

Desired state:

```cisco
interface <guest-subinterface>
 ip access-group GUEST_TO_FINANCE in
```

Injected drift: the inbound ACL attachment is absent.

Minimal repair:

```cisco
interface <guest-subinterface>
 ip access-group GUEST_TO_FINANCE in
```

Expected policy behaviour (provided addressing and routing are healthy): employee-to-finance is permitted; guest-to-finance is denied by the ACL. ICMP results alone do not prove the ACL caused a drop; use the configuration diff, ACL attachment and counter evidence.

## Scope and recovery

The 1.2.0 semantic reconciler covers named router IPv4 ACL attachments only. It does not automatically repair VLAN, DHCP, OSPF, static route, switch port-security or host-addressing drift. If a command fails or execution is partial, stop and inspect the transaction report and device configuration before retrying. Checkpoints are local evidence; automatic atomic rollback is not claimed.

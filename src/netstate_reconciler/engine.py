from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .binding import interfaces_for_device, normalize_interface_name
from .compiler import DeviceConfig, compile_host_settings, compile_intent
from .config_drift import classify_capture, config_diff, redact_output
from .mcp_client import MCPToolError, MCPToolbox, result_failed, result_text
from .models import NetworkIntent
from .reconcile import (
    acl_drift_simulation_command,
    compare_acl_attachments,
    parse_ios_config,
)
from .security import ProbeAssessment, assess_reachability
from .topology import TopologyInventory, merge_inventories, parse_topology


@dataclass
class ExecutionStep:
    device: str
    command_count: int
    status: str
    detail: str = ""


@dataclass
class ExecutionReport:
    transaction_id: str
    started_at: str
    completed_at: str
    status: str
    steps: list[ExecutionStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checkpoint_files: list[str] = field(default_factory=list)
    note: str = ""


class StateStore:
    def __init__(self, root: str | Path = ".netstate"):
        self.root = Path(root)
        self.checkpoints = self.root / "checkpoints"
        self.reports = self.root / "reports"
        self.snapshots = self.root / "snapshots"
        for path in (self.checkpoints, self.reports, self.snapshots):
            path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass

    def write_json(self, folder: Path, name: str, payload: Any) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        path = folder / safe_name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def save_report(self, report: ExecutionReport) -> Path:
        return self.write_json(self.reports, f"{report.transaction_id}.json", asdict(report))

    def save_topology_snapshot(self, inventory: TopologyInventory, label: str = "baseline") -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.write_json(self.snapshots, f"{label}-{stamp}.json", inventory.to_dict())

    def save_topology_baseline(self, inventory: TopologyInventory) -> Path:
        self.save_topology_snapshot(inventory, "topology-capture")
        return self.write_json(self.snapshots, "topology-baseline.json", inventory.to_dict())

    def load_topology_baseline(self) -> dict[str, Any] | None:
        path = self.snapshots / "topology-baseline.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_config_baseline(self, configs: dict[str, dict[str, str]]) -> Path:
        return self.write_json(self.snapshots, "running-config-baseline.json", configs)

    def load_config_baseline(self) -> dict[str, dict[str, str]] | None:
        path = self.snapshots / "running-config-baseline.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_desired_intent(self, intent: NetworkIntent) -> Path:
        payload = intent.model_dump(mode="json")
        self.write_json(self.snapshots, "desired-state.json", payload)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.write_json(self.snapshots, f"desired-state-{stamp}.json", payload)

    def load_desired_intent(self) -> NetworkIntent | None:
        path = self.snapshots / "desired-state.json"
        if not path.exists():
            return None
        return NetworkIntent.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_checkpoint(self, device: str, payload: Any, transaction_id: str) -> Path:
        # Config checkpoints can contain credentials. They are local-only and permission-restricted.
        return self.write_json(self.checkpoints, f"{transaction_id}-{device}-checkpoint.json", payload)


def validate_intent_against_inventory(intent: NetworkIntent, inventory: TopologyInventory) -> list[str]:
    problems: list[str] = []
    requested: dict[str, str] = {}
    requested.update({name: "router" for name in intent.routers})
    requested.update({name: "switch" for name in intent.switches})
    requested.update({name: "host" for name in intent.hosts})
    known = {name.casefold(): item for name, item in ((item.name, item) for item in inventory.devices)}
    for name, role in requested.items():
        device = known.get(name.casefold())
        if device is None:
            problems.append(f"{role.title()} `{name}` is not present in the discovered Packet Tracer topology.")
            continue
        model_hint = f"{device.model} {device.category}".lower()
        router_hints = ("router", "2911", "1941", "1841", "2901", "4321", "4331")
        switch_hints = ("switch", "2960", "2950", "3560", "3650", "3750")
        if role == "router" and any(hint in model_hint for hint in switch_hints):
            problems.append(f"{name} is declared as a router but the discovered model/category looks like a switch ({device.model}/{device.category}).")
        if role == "switch" and any(hint in model_hint for hint in router_hints):
            problems.append(f"{name} is declared as a switch but the discovered model/category looks like a router ({device.model}/{device.category}).")
        if role == "host" and any(hint in model_hint for hint in (*router_hints, *switch_hints)):
            problems.append(f"{name} is declared as a host but the discovered model/category looks like network infrastructure ({device.model}/{device.category}).")
        if role in {"router", "switch"}:
            actual = {
                normalize_interface_name(interface)
                for interface in interfaces_for_device(inventory, device.name)
            }
            config = intent.routers.get(name) or intent.switches.get(name)
            configured_interfaces: list[str] = []
            if intent.routers.get(name):
                configured_interfaces.extend(intent.routers[name].interfaces)
                configured_interfaces.extend(subif.parent_interface for subif in intent.routers[name].subinterfaces.values())
                configured_interfaces.extend(acl.interface.split(".", 1)[0] for acl in intent.routers[name].acls)
            if intent.switches.get(name):
                configured_interfaces.extend(port.interface for port in intent.switches[name].access_ports)
                configured_interfaces.extend(port.interface for port in intent.switches[name].trunk_ports)
            for interface in configured_interfaces:
                physical_name = interface.rsplit(".", 1)[0] if "." in interface and interface.rsplit(".", 1)[1].isdigit() else interface
                if normalize_interface_name(physical_name) not in actual:
                    problems.append(f"{name}: interface `{interface}` was not found in discovered inventory (Cisco abbreviations are normalized).")
    return problems


class NetStateEngine:
    def __init__(self, toolbox: MCPToolbox, store: StateStore | None = None):
        self.toolbox = toolbox
        self.store = store or StateStore()
        self.inventory: TopologyInventory | None = None
        self.last_discovery_diagnostic: dict[str, Any] | None = None

    def connect(self) -> dict[str, Any]:
        tools = self.toolbox.refresh()
        status_name = self.toolbox.has("pt_bridge_status")
        bridge: dict[str, Any] | None = None
        bridge_connected: bool | None = None
        if status_name:
            bridge = self.toolbox.invoke(status_name)
            structured = bridge.get("structured") if isinstance(bridge, dict) else None
            if isinstance(structured, dict):
                for key in ("connected", "bridge_connected", "active"):
                    if isinstance(structured.get(key), bool):
                        bridge_connected = structured[key]
                        break
            lower = result_text(bridge).lower()
            if bridge_connected is None:
                negative = any(token in lower for token in ("not connected", "disconnected", "offline", "down"))
                positive = any(token in lower for token in ("active and connected", "connected", "active", "http bridge", "file-bridge"))
                if negative:
                    bridge_connected = False
                elif positive:
                    bridge_connected = True
        return {
            "endpoint_reachable": True,
            "tool_count": len(tools),
            "tool_names": [tool.name for tool in tools],
            "bridge_tool_available": bool(status_name),
            "bridge_connected": bridge_connected,
            "bridge_result": bridge,
        }

    def discover(self) -> TopologyInventory:
        """Discover devices from both MCP topology views and combine their detail.

        pt_export_topology is preferred for physical links and connected ports;
        pt_query_topology supplements it with the complete interface catalog.
        The two views are intentionally queried independently because MCP 0.10.x
        returns human-readable text rather than structured device arrays.
        """
        export_tool = self.toolbox.has("pt_export_topology")
        query_tool = self.toolbox.has("pt_query_topology")
        if not export_tool and not query_tool:
            raise MCPToolError("The server exposes neither pt_export_topology nor pt_query_topology.")

        export_result: dict[str, Any] | None = None
        query_result: dict[str, Any] | None = None
        errors: list[str] = []
        if export_tool:
            try:
                export_result = self.toolbox.invoke(export_tool)
            except Exception as exc:
                errors.append(f"{export_tool}: {exc}")
        if query_tool:
            try:
                query_result = self.toolbox.invoke(query_tool)
            except Exception as exc:
                errors.append(f"{query_tool}: {exc}")

        export_inventory = parse_topology(export_result) if export_result is not None else TopologyInventory()
        query_inventory = parse_topology(query_result) if query_result is not None else TopologyInventory()
        if export_inventory.devices and query_inventory.devices:
            inventory = merge_inventories(export_inventory, query_inventory)
        elif export_inventory.devices:
            inventory = export_inventory
        else:
            inventory = query_inventory
        inventory.raw = {
            "pt_export_topology": export_result,
            "pt_query_topology": query_result,
            "discovery_errors": errors,
        }
        self.last_discovery_diagnostic = {
            "status": "success" if inventory.devices else "empty_inventory",
            "export_devices_parsed": len(export_inventory.devices),
            "export_links_parsed": len(export_inventory.links),
            "query_devices_parsed": len(query_inventory.devices),
            "query_links_parsed": len(query_inventory.links),
            "merged_devices": len(inventory.devices),
            "merged_links": len(inventory.links),
            "errors": errors,
            "raw": inventory.raw,
        }
        if not inventory.devices:
            detail = "\n".join(errors) if errors else "Both topology tools returned no parseable devices."
            raise MCPToolError(
                "Packet Tracer returned topology responses, but NetState could not extract a device inventory. "
                "Open the discovery diagnostic below to inspect the exact MCP payloads.\n" + detail
            )
        self.inventory = inventory
        return inventory

    def create_checkpoint(self, device: str, transaction_id: str) -> Path | None:
        tool = self.toolbox.has("pt_backup_config")
        if not tool:
            return None
        result = self.toolbox.invoke(tool, {"device": device, "include_xml": False})
        if result_failed(result):
            raise MCPToolError(f"Configuration checkpoint failed for {device}: {result_text(result)}")
        return self.store.save_checkpoint(device, result, transaction_id)

    def _run_device_config(self, device_config: DeviceConfig) -> ExecutionStep:
        responses = self.toolbox.cli(device_config.device, list(device_config.commands))
        failed = next((response for response in responses if result_failed(response)), None)
        if failed:
            detail = redact_output(result_text(failed))[:3000]
            return ExecutionStep(device_config.device, len(device_config.commands), "FAILED", detail)
        return ExecutionStep(
            device_config.device, len(device_config.commands), "SUBMITTED",
            "Command batch returned without a recognised MCP error. Read-back verification is still required.",
        )

    def apply_intent(
        self,
        intent: NetworkIntent,
        approved: bool,
        allow_without_checkpoint: bool = False,
        security: dict[str, str] | None = None,
    ) -> ExecutionReport:
        started = datetime.now(timezone.utc).isoformat()
        transaction_id = uuid.uuid4().hex[:12]
        report = ExecutionReport(
            transaction_id=transaction_id,
            started_at=started,
            completed_at="",
            status="BLOCKED",
        )
        if not approved:
            report.errors.append("Operator approval was not provided.")
            report.completed_at = datetime.now(timezone.utc).isoformat()
            return report
        if self.inventory is None:
            report.errors.append("Discover the live Packet Tracer topology before applying configuration.")
            report.completed_at = datetime.now(timezone.utc).isoformat()
            return report
        problems = validate_intent_against_inventory(intent, self.inventory)
        if problems:
            report.errors.extend(problems)
            report.completed_at = datetime.now(timezone.utc).isoformat()
            return report
        device_configs = compile_intent(intent, security)
        host_settings = compile_host_settings(intent)
        # IOS configuration checkpoints are taken for routers/switches. Packet Tracer hosts
        # use the Desktop IP Configuration panel and do not expose the same IOS backup tool.
        device_names = [config.device for config in device_configs]
        checkpoint_failures: list[str] = []
        for device in device_names:
            try:
                checkpoint = self.create_checkpoint(device, transaction_id)
                if checkpoint:
                    report.checkpoint_files.append(str(checkpoint))
                else:
                    checkpoint_failures.append(f"{device}: pt_backup_config unavailable")
            except Exception as exc:
                checkpoint_failures.append(f"{device}: {exc}")
        if checkpoint_failures and not allow_without_checkpoint:
            report.status = "BLOCKED"
            report.errors.extend(checkpoint_failures)
            report.errors.append("No device configuration was changed. Resolve checkpoint failures or explicitly acknowledge proceeding without checkpoints.")
            report.completed_at = datetime.now(timezone.utc).isoformat()
            self.store.save_report(report)
            return report

        report.status = "PARTIAL_OR_UNVERIFIED"
        for config in device_configs:
            try:
                step = self._run_device_config(config)
            except Exception as exc:
                step = ExecutionStep(config.device, 0, "FAILED", str(exc))
            report.steps.append(step)
            if step.status == "FAILED":
                report.errors.append(f"Execution stopped after failure on {config.device}.")
                report.status = "PARTIAL_FAILURE"
                break
        else:
            for host, values in host_settings.items():
                try:
                    result = self.toolbox.invoke("pt_host_ip_config", {"device": host, **values})
                    failed = result_failed(result)
                    step = ExecutionStep(host, 1, "FAILED" if failed else "SUBMITTED", result_text(result)[:1200])
                except Exception as exc:
                    step = ExecutionStep(host, 0, "FAILED", str(exc))
                report.steps.append(step)
                if step.status == "FAILED":
                    report.errors.append(f"Execution stopped after host configuration failed on {host}.")
                    report.status = "PARTIAL_FAILURE"
                    break
        if host_settings:
            report.note = "End-host IP settings do not have an IOS startup-config checkpoint. "
        if checkpoint_failures:
            report.note += "Some IOS devices were configured without a successful MCP checkpoint. "
        report.note += "Submitted commands are not proof of network correctness. Run verification before declaring success. "
        report.note += "If a multi-device operation fails, the application stops; it does not claim an atomic rollback."
        report.completed_at = datetime.now(timezone.utc).isoformat()
        self.store.save_report(report)
        return report

    def _acl_counter_snapshot(self, inventory: TopologyInventory) -> dict[str, str]:
        """Best-effort read-only snapshot of ACL counters and interface attachment on routers."""
        snapshots = {}
        for device in inventory.devices:
            hint = f"{device.model} {device.category}".lower()
            if not any(x in hint for x in ("router", "2911", "1941", "1841", "2901", "4321", "4331", "isr")):
                continue
            try:
                responses = self.toolbox.cli(device.name, ["show access-lists", "show ip interface"])
                snapshots[device.name] = "\n".join(result_text(r) for r in responses)
            except Exception:
                # Lack of CLI evidence must never be treated as policy confirmation.
                continue
        return snapshots

    def verify_connectivity(self, source_device: str, destination_ip: str) -> ProbeAssessment:
        from ipaddress import IPv4Address
        try:
            destination_ip = str(IPv4Address(destination_ip))
        except ValueError as exc:
            raise ValueError(f"Invalid IPv4 destination address: {destination_ip!r}") from exc

        inventory = self.discover()
        source = next((d for d in inventory.devices if d.name.casefold() == source_device.casefold()), None)
        source_ip = source.ip_addresses[0] if source and source.ip_addresses else None
        before = self._acl_counter_snapshot(inventory)
        _, result = self.toolbox.invoke_first(
            ("pt_verify_connectivity",),
            {"from_device": source_device, "to_ip": destination_ip, "timeout": 45},
        )
        after = self._acl_counter_snapshot(inventory)
        from .security import confirm_policy_block
        policy = confirm_policy_block(before, after, source_ip, destination_ip)
        return assess_reachability(result, policy)
    def security_audit(self) -> dict[str, Any]:
        _, result = self.toolbox.invoke_first(("pt_audit_security",))
        return result

    def save_project(self, filename: str) -> dict[str, Any]:
        safe = Path(filename).name
        if not safe.lower().endswith(".pkt"):
            safe += ".pkt"
        _, result = self.toolbox.invoke_first(("pt_save_project",), {"filename": safe})
        return result

    def capture_config(self, device: str) -> dict[str, Any]:
        tool = self.toolbox.has("pt_cli", "pt_run_cli_bulk", "pt_run_cli")
        if not tool:
            raise MCPToolError("The connected server exposes no supported CLI read tool.")
        responses = self.toolbox.cli(device, ["show running-config"])
        if not responses:
            raise MCPToolError(f"No CLI response was returned for {device}.")
        return responses[0]

    def capture_config_baseline(self, devices: list[str]) -> dict[str, dict[str, str]]:
        captured: dict[str, dict[str, str]] = {}
        failures: list[str] = []
        for device in devices:
            try:
                raw = self.capture_config(device)
                redacted, digest = classify_capture(raw, device)
                captured[device] = {"config": redacted, "sha256": digest}
            except Exception as exc:
                failures.append(f"{device}: {exc}")
        if failures:
            raise MCPToolError("Running-config baseline was not saved because capture was incomplete:\n" + "\n".join(failures))
        self.store.save_config_baseline(captured)
        return captured

    def compare_config_baseline(self, devices: list[str]) -> dict[str, str]:
        baseline = self.store.load_config_baseline()
        if baseline is None:
            raise MCPToolError("No running-config baseline exists. Capture one first.")
        diffs: dict[str, str] = {}
        missing = sorted(set(devices) - set(baseline))
        if missing:
            raise MCPToolError("Devices missing from the config baseline: " + ", ".join(missing))
        for device in devices:
            raw = self.capture_config(device)
            redacted, _ = classify_capture(raw, device)
            diff = config_diff(baseline[device]["config"], redacted, device)
            if diff:
                diffs[device] = diff
        return diffs

    def capture_configs(self, devices: list[str]) -> dict[str, str]:
        """Capture redacted running configs for every requested device or fail closed."""
        captured: dict[str, str] = {}
        failures: list[str] = []
        for device in devices:
            try:
                raw = self.capture_config(device)
                redacted, _ = classify_capture(raw, device)
                captured[device] = redacted
            except Exception as exc:
                failures.append(f"{device}: {exc}")
        if failures:
            raise MCPToolError(
                "Configuration collection was incomplete; no compliance result was produced:\n"
                + "\n".join(failures)
            )
        return captured

    def analyze_intent_drift(self, intent: NetworkIntent) -> dict[str, Any]:
        """Compare live ACL attachments against the mapped desired intent.

        The first semantic reconciliation release deliberately scopes automatic
        classification to named ACL attachments, the control used by the demo.
        Other configuration families are not silently claimed as compliant.
        """
        devices = list(intent.routers)
        if not devices:
            raise MCPToolError("The desired intent contains no routers with configuration to inspect.")
        configs = self.capture_configs(devices)
        findings = compare_acl_attachments(intent, configs)
        return {
            "scope": "named ACL attachments on intent routers",
            "devices_audited": len(configs),
            "findings": [item.to_dict() for item in findings],
            "compliant": not findings,
            "configs": configs,
        }

    def simulate_acl_attachment_drift(
        self, intent: NetworkIntent, device: str, acl_name: str,
        approved: bool, allow_without_checkpoint: bool = False,
    ) -> dict[str, Any]:
        """Remove one existing ACL attachment as a controlled lab fault injection."""
        if not approved:
            raise MCPToolError("Simulation blocked: operator approval was not provided.")
        interface, direction, removal_command = acl_drift_simulation_command(intent, device, acl_name)
        before = self.capture_configs([device])[device]
        facts = parse_ios_config(before)
        key = normalize_interface_name(interface)
        observed = facts.interfaces.get(key)
        if observed is None:
            raise MCPToolError(f"Simulation blocked: {device}/{interface} was not found in running-config.")
        attached = observed["acl_attachments"].get(direction)
        if not attached or attached.casefold() != acl_name.casefold():
            raise MCPToolError(
                f"Simulation blocked: expected {acl_name} ({direction}) on {device}/{interface}, "
                f"but observed {attached or 'no ACL'}. The simulation will not overwrite an unknown state."
            )
        defined_acl = acl_name.casefold() in facts.acl_definitions
        if not defined_acl:
            raise MCPToolError(f"Simulation blocked: ACL definition {acl_name} was not found on {device}.")

        transaction_id = uuid.uuid4().hex[:12]
        checkpoint = None
        try:
            checkpoint = self.create_checkpoint(device, transaction_id)
        except Exception as exc:
            if not allow_without_checkpoint:
                raise MCPToolError(f"Simulation blocked because checkpoint creation failed: {exc}") from exc
        if checkpoint is None and not allow_without_checkpoint:
            raise MCPToolError(
                "Simulation blocked because pt_backup_config is unavailable. "
                "Save the .pkt project or explicitly acknowledge proceeding without a device checkpoint."
            )

        commands = ["configure terminal", f"interface {interface}", removal_command, "exit", "end", "write memory"]
        responses = self.toolbox.cli(device, commands)
        failed = next((item for item in responses if result_failed(item)), None)
        if failed:
            return {
                "status": "PARTIAL_FAILURE", "transaction_id": transaction_id,
                "device": device, "interface": interface, "acl": acl_name,
                "detail": redact_output(result_text(failed))[:3000],
                "checkpoint": str(checkpoint) if checkpoint else None,
            }
        try:
            after = self.capture_configs([device])[device]
            after_facts = parse_ios_config(after)
            after_attachment = after_facts.interfaces.get(key, {}).get("acl_attachments", {}).get(direction)
            verified = not after_attachment or after_attachment.casefold() != acl_name.casefold()
            status = "DRIFT_INJECTED" if verified else "UNVERIFIED"
            return {
                "status": status, "transaction_id": transaction_id,
                "device": device, "interface": interface, "acl": acl_name,
                "direction": direction, "before": attached,
                "after": after_attachment or "No ACL",
                "verified": verified,
                "detail": "Read-back confirms the ACL attachment was removed." if verified else
                          "The CLI returned without an error, but read-back still shows the ACL attachment.",
                "checkpoint": str(checkpoint) if checkpoint else None,
            }
        except Exception as exc:
            return {
                "status": "APPLIED_UNVERIFIED", "transaction_id": transaction_id,
                "device": device, "interface": interface, "acl": acl_name,
                "direction": direction, "verified": False,
                "detail": f"Change was submitted but read-back failed: {exc}",
                "checkpoint": str(checkpoint) if checkpoint else None,
            }

    def remediate_acl_drift(
        self, intent: NetworkIntent, approved: bool,
        allow_without_checkpoint: bool = False,
    ) -> dict[str, Any]:
        """Apply only missing/wrong named ACL attachments, then independently verify."""
        transaction_id = uuid.uuid4().hex[:12]
        if not approved:
            return {"status": "BLOCKED", "transaction_id": transaction_id, "reason": "Operator approval was not provided."}
        analysis = self.analyze_intent_drift(intent)
        findings = analysis["findings"]
        if not findings:
            return {
                "status": "NO_DRIFT", "transaction_id": transaction_id,
                "message": "All supported ACL attachment checks match the desired intent.",
                "before_findings": [], "after_findings": [], "steps": [],
            }
        unsupported = [item for item in findings if not item.get("auto_remediable")]
        if unsupported:
            return {
                "status": "BLOCKED", "transaction_id": transaction_id,
                "reason": "Some findings are not safe for automatic repair. Resolve or inspect them manually.",
                "unsupported_findings": unsupported, "before_findings": findings,
            }

        affected = sorted({item["device"] for item in findings})
        checkpoints: dict[str, str] = {}
        checkpoint_failures: list[str] = []
        for device in affected:
            try:
                checkpoint = self.create_checkpoint(device, transaction_id)
                if checkpoint:
                    checkpoints[device] = str(checkpoint)
                else:
                    checkpoint_failures.append(f"{device}: pt_backup_config unavailable")
            except Exception as exc:
                checkpoint_failures.append(f"{device}: {exc}")
        if checkpoint_failures and not allow_without_checkpoint:
            return {
                "status": "BLOCKED", "transaction_id": transaction_id,
                "reason": "No device changes were made because a checkpoint could not be created.",
                "checkpoint_failures": checkpoint_failures, "before_findings": findings,
            }

        by_device: dict[str, list[dict[str, Any]]] = {}
        for finding in findings:
            by_device.setdefault(finding["device"], []).append(finding)
        steps: list[dict[str, Any]] = []
        for device, device_findings in by_device.items():
            # Each remediation is intentionally narrow: attach the existing ACL.
            commands = ["configure terminal"]
            for finding in device_findings:
                interface = finding["object_name"]
                acl_name, direction = finding["expected"].rsplit(" (", 1)
                direction = direction.rstrip(")")
                commands.extend([f"interface {interface}", f"ip access-group {acl_name} {direction}", "exit"])
            commands.extend(["end", "write memory"])
            try:
                responses = self.toolbox.cli(device, commands)
                failed = next((item for item in responses if result_failed(item)), None)
                if failed:
                    steps.append({
                        "device": device, "status": "FAILED", "commands": commands,
                        "detail": redact_output(result_text(failed))[:3000],
                    })
                    break
                steps.append({"device": device, "status": "SUBMITTED", "commands": commands, "detail": "CLI batch returned without a recognized error."})
            except Exception as exc:
                steps.append({"device": device, "status": "FAILED", "commands": commands, "detail": str(exc)})
                break

        failed_step = next((step for step in steps if step["status"] == "FAILED"), None)
        try:
            after_analysis = self.analyze_intent_drift(intent)
            remaining = after_analysis["findings"]
        except Exception as exc:
            remaining = None
            verification_error = str(exc)
        else:
            verification_error = ""
        if failed_step:
            status = "PARTIAL_FAILURE"
        elif remaining is None:
            status = "APPLIED_UNVERIFIED"
        elif remaining:
            status = "PARTIAL"
        else:
            status = "VERIFIED"
        return {
            "status": status, "transaction_id": transaction_id,
            "before_findings": findings, "after_findings": remaining,
            "steps": steps, "checkpoints": checkpoints,
            "checkpoint_failures": checkpoint_failures,
            "verification_error": verification_error,
            "message": (
                "Live read-back confirms all targeted ACL attachments match the desired intent."
                if status == "VERIFIED" else
                "Commands were submitted, but the desired state was not fully verified. Inspect the device results."
            ),
        }

    def health_check(self) -> dict[str, Any]:
        _, result = self.toolbox.invoke_first(("pt_health_check",))
        return result

    def collect_packet_trace(self) -> dict[str, Any]:
        _, result = self.toolbox.invoke_first(("pt_read_packet_trace",))
        return result

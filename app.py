from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from netstate_reconciler import __version__  # noqa: E402
from netstate_reconciler.binding import (  # noqa: E402
    bind_intent_to_inventory,
    interface_references,
    interfaces_for_device,
    load_device_bindings,
    save_device_bindings,
    suggest_interface_binding,
    topology_fingerprint,
    validate_device_bindings,
)
from netstate_reconciler.compiler import CompileError, compile_intent  # noqa: E402
from netstate_reconciler.drift import compare_topology  # noqa: E402
from netstate_reconciler.deployment import persist_topology_plan, tool_plan_arguments  # noqa: E402
from netstate_reconciler.engine import NetStateEngine, StateStore, validate_intent_against_inventory  # noqa: E402
from netstate_reconciler.intent import IntentError, load_intent  # noqa: E402
from netstate_reconciler.mcp_client import MCPConnectionError, MCPHTTPClient, MCPToolError, MCPToolbox, result_failed, result_text  # noqa: E402
from netstate_reconciler.models import NetworkIntent  # noqa: E402


st.set_page_config(page_title="NetState Reconciler", page_icon="◈", layout="wide")

CSS = """
<style>
:root { color-scheme: dark; }
.block-container { padding-top: 1.4rem; max-width: 1500px; }
[data-testid="stAppViewContainer"] { background: #0b1020; }
[data-testid="stHeader"] { background: rgba(0,0,0,0); }
[data-testid="stSidebar"] { background: #111a2e; }
.ns-hero { background: linear-gradient(120deg,#142944,#17233b 60%,#132e38); border: 1px solid #29435b; border-radius: 18px; padding: 24px 28px; margin-bottom: 20px; }
.ns-eyebrow { color: #70d6c2; font-size: 0.76rem; letter-spacing: .17em; font-weight: 700; text-transform: uppercase; }
.ns-title { color: #f2f6ff; font-size: 2.1rem; font-weight: 750; margin: 6px 0; }
.ns-sub { color: #b8c7da; font-size: 1rem; }
.ns-card { background:#121c30; border:1px solid #263a54; border-radius:14px; padding:16px 18px; min-height:110px; }
.ns-card-label { color:#8fa7c4; font-size:.76rem; letter-spacing:.08em; text-transform:uppercase; }
.ns-card-value { color:#f1f6ff; font-size:1.55rem; font-weight:700; margin-top:8px; }
div[data-testid="stMetric"] { background:#121c30; border:1px solid #263a54; padding:12px 16px; border-radius:12px; }
.stButton > button { border-radius:9px; font-weight:650; }
section[data-testid="stSidebar"] .stButton > button { width:100%; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

DEFAULT_ENDPOINT = os.getenv("NETSTATE_MCP_ENDPOINT", "http://127.0.0.1:39400/mcp")


def get_engine(endpoint: str) -> NetStateEngine:
    current_endpoint = st.session_state.get("endpoint")
    if "engine" not in st.session_state or current_endpoint != endpoint:
        client = MCPHTTPClient(endpoint=endpoint, timeout=60)
        toolbox = MCPToolbox(client)
        st.session_state.engine = NetStateEngine(toolbox, StateStore(ROOT / ".netstate"))
        st.session_state.endpoint = endpoint
        st.session_state.connected = False
        st.session_state.connection_info = None
        st.session_state.inventory = None
        st.session_state.baseline = None
    return st.session_state.engine


def render_device_interface_mapping(intent, inventory):
    """Render persistent logical-role to live-device/interface bindings."""
    binding_path = ROOT / ".netstate" / "device-bindings.json"
    saved = load_device_bindings(binding_path)
    current_fingerprint = topology_fingerprint(inventory)
    previous_fingerprint = st.session_state.get("netstate_binding_topology_fingerprint")
    if previous_fingerprint and previous_fingerprint != current_fingerprint:
        for key in list(st.session_state.keys()):
            if (key.startswith("netstate_bind_device::")
                    or key.startswith("netstate_bind_interface::")
                    or key.startswith("netstate_last_device::")):
                del st.session_state[key]
        st.warning("The discovered topology changed. Previous widget selections were cleared; review all device and interface bindings again.")
    st.session_state["netstate_binding_topology_fingerprint"] = current_fingerprint
    if saved.get("fingerprint") and saved["fingerprint"] != current_fingerprint:
        st.warning("Saved mappings belong to a different device/link topology. They will not be reused automatically.")
        saved = {"devices": {}, "interfaces": {}, "fingerprint": saved.get("fingerprint")}
    logical_roles = []
    logical_roles.extend((name, "router") for name in intent.routers)
    logical_roles.extend((name, "switch") for name in intent.switches)
    logical_roles.extend((name, "host") for name in intent.hosts)
    all_devices = [item for item in inventory.devices if item.category.casefold() != "auxiliary"]
    all_names = [item.name for item in all_devices]

    def role_candidates(role):
        hints = {
            "router": ("router", "2911", "1941", "1841", "2901", "4321", "4331", "isr"),
            "switch": ("switch", "2960", "2950", "3560", "3650", "3750"),
            "host": ("pc", "server", "laptop", "ip phone", "end device"),
        }.get(role, ())
        matching = [
            item.name for item in all_devices
            if item.category.casefold() == role
            or any(token in (item.model + " " + item.category).casefold() for token in hints)
        ]
        return matching or all_names

    st.markdown("#### Device & interface mapping")
    st.caption(
        "Map the logical names used by the intent (R1, SW1, PC-EMPLOYEE, etc.) "
        "to the devices actually discovered in Packet Tracer. The physical topology is not renamed or modified."
    )
    device_mapping = {}
    for logical_name, role in logical_roles:
        options = ["— Select device —"] + role_candidates(role)
        key = f"netstate_bind_device::{logical_name}"
        if key not in st.session_state:
            initial = saved.get("devices", {}).get(logical_name, logical_name)
            st.session_state[key] = initial if initial in options else "— Select device —"
        if st.session_state.get(key) not in options:
            st.session_state[key] = "— Select device —"
        chosen = st.selectbox(
            f"{logical_name} · {role}", options, key=key,
            help="Choose the discovered Packet Tracer device that represents this logical role.",
        )
        last_device_key = f"netstate_last_device::{logical_name}"
        previous_device = st.session_state.get(last_device_key)
        if previous_device is not None and previous_device != chosen:
            interface_prefix = f"netstate_bind_interface::{logical_name}::"
            for state_key in list(st.session_state.keys()):
                if state_key.startswith(interface_prefix):
                    del st.session_state[state_key]
            saved.setdefault("interfaces", {})[logical_name] = {}
        st.session_state[last_device_key] = chosen
        if chosen != "— Select device —":
            device_mapping[logical_name] = chosen

    duplicate_devices = {}
    for logical_name, actual_name in device_mapping.items():
        duplicate_devices.setdefault(actual_name.casefold(), []).append(logical_name)
    for aliases in duplicate_devices.values():
        if len(aliases) > 1:
            st.error(f"The same discovered device is assigned to multiple roles: {', '.join(aliases)}.")

    interface_mapping = {}
    with st.expander("Map physical interfaces", expanded=True):
        st.caption(
            "Suggestions use Cisco interface-name normalization and observed physical links. "
            "Review every mapping; subinterfaces such as Gi0/0.10 are derived from their mapped parent."
        )
        for logical_name, role in logical_roles:
            if role not in {"router", "switch"}:
                continue
            actual_device = device_mapping.get(logical_name)
            if not actual_device:
                st.info(f"Select a discovered device for {logical_name} before mapping its interfaces.")
                continue
            candidates = interfaces_for_device(inventory, actual_device)
            if not candidates:
                st.warning(f"No interface inventory was returned for {actual_device}.")
                continue
            per_device = {}
            for logical_interface in interface_references(intent, logical_name):
                key = f"netstate_bind_interface::{logical_name}::{logical_interface}"
                suggestion = suggest_interface_binding(
                    intent, inventory, logical_name, actual_device,
                    logical_interface, device_mapping,
                )
                saved_value = saved.get("interfaces", {}).get(logical_name, {}).get(logical_interface)
                initial = saved_value if saved_value in candidates else suggestion
                options = ["— Select interface —"] + candidates
                if key not in st.session_state:
                    st.session_state[key] = initial if initial in candidates else "— Select interface —"
                if st.session_state.get(key) not in options:
                    st.session_state[key] = initial if initial in candidates else "— Select interface —"
                chosen = st.selectbox(
                    f"{logical_name} · {logical_interface}", options, key=key,
                    help=(f"Actual physical interface on {actual_device}. "
                          f"Topology-based suggestion: {suggestion}" if suggestion else
                          f"Choose the physical interface on {actual_device}."),
                )
                if suggestion:
                    st.caption(f"Topology suggestion for {logical_name}/{logical_interface}: `{suggestion}`")
                if chosen != "— Select interface —":
                    per_device[logical_interface] = chosen
            interface_mapping[logical_name] = per_device

    current = {"devices": device_mapping, "interfaces": interface_mapping}
    mapping_problems = validate_device_bindings(intent, current, inventory)
    save_col, status_col = st.columns([1, 2])
    with save_col:
        if st.button("Save device & interface mappings", key="save_device_interface_mappings"):
            save_device_bindings(binding_path, current, current_fingerprint)
            st.success("Mappings saved locally.")
    with status_col:
        if mapping_problems:
            st.warning(f"Mapping incomplete · {len(mapping_problems)} issue(s) remain.")
        else:
            st.success("All logical devices and configured physical interfaces are bound to discovered inventory.")
    if mapping_problems:
        with st.expander("Mapping validation details", expanded=True):
            for problem in mapping_problems:
                st.error(problem)
        return None, mapping_problems, current
    try:
        mapped = bind_intent_to_inventory(intent, current, inventory)
        return mapped, [], current
    except Exception as exc:
        errors = [str(exc)]
        st.error(f"Could not construct mapped intent: {exc}")
        return None, errors, current


def show_result(title: str, result: object) -> None:
    with st.expander(title, expanded=False):
        st.code(result_text(result) or json.dumps(result, indent=2, default=str), language="text")



def _json_from_text(value: str) -> object | None:
    """Extract a JSON value from a complete or decorated MCP text response."""
    candidate = value.strip()
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(candidate[index:])
            return parsed
        except json.JSONDecodeError:
            continue
    return None


def _extract_plan_payload(result: object) -> object | None:
    """Find the actual plan object in the different MCP result envelopes."""
    seen: set[int] = set()

    def walk(value: object) -> object | None:
        if id(value) in seen:
            return None
        if isinstance(value, (dict, list)):
            seen.add(id(value))
        if isinstance(value, dict):
            keys = {str(key).lower() for key in value}
            if ("devices" in keys or "nodes" in keys) and ("links" in keys or "connections" in keys):
                return value
            # Prefer likely wrapper keys before traversing the whole response.
            for key in ("plan", "topology_plan", "plan_json", "structured", "structuredcontent", "result", "data", "output"):
                if key in value:
                    candidate = walk(value[key])
                    if candidate is not None:
                        return candidate
            for nested in value.values():
                candidate = walk(nested)
                if candidate is not None:
                    return candidate
        elif isinstance(value, list):
            for nested in value:
                candidate = walk(nested)
                if candidate is not None:
                    return candidate
        elif isinstance(value, str):
            parsed = _json_from_text(value)
            if parsed is not None:
                return walk(parsed)
        return None

    return walk(result)


def _tool_plan_arguments(
    descriptor: object, plan_payload: object, plan_file_path: Path
) -> dict[str, object]:
    """Build MCP arguments with a real JSON file for plan_path fields."""
    return tool_plan_arguments(descriptor, plan_payload, plan_file_path)


def _explicit_validation_errors(result: object) -> list[str]:
    """Return explicit validator errors, while accepting text-only success responses."""
    raw = result.get("structured") if isinstance(result, dict) else None
    if raw is None and isinstance(result, dict):
        raw = result.get("parsed_text")
    values = [raw] if raw is not None else []
    values.append(_json_from_text(result_text(result)))
    for value in values:
        stack = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, list):
                stack.extend(current)
            elif isinstance(current, dict):
                valid = current.get("valid")
                errors = current.get("errors")
                if valid is False:
                    if isinstance(errors, list) and errors:
                        return [str(item) for item in errors]
                    return ["The MCP validator marked this topology invalid."]
                if isinstance(errors, list) and errors:
                    return [str(item) for item in errors]
                stack.extend(current.values())
    return []


def graph_dot(inventory: object) -> str:
    def quote(value: str) -> str:
        return '"' + value.replace('"', '\\"') + '"'

    rows = ["graph NetState {", "  graph [bgcolor=\"#0b1020\", fontname=\"Arial\", overlap=false, splines=true];", "  node [style=filled, fillcolor=\"#18314b\", color=\"#4c7892\", fontcolor=\"#edf5ff\", fontname=\"Arial\", shape=box];", "  edge [color=\"#6b9ca9\", fontcolor=\"#d3e4ec\", fontname=\"Arial\"]; "]
    for device in inventory.devices:
        model = device.model if device.model != "Unknown" else device.category
        rows.append(f"  {quote(device.name)} [label={quote(device.name + '\\n' + model)}];")
    for link in inventory.links:
        label = f"{link.source_port} ↔ {link.target_port}".strip(" ↔")
        rows.append(f"  {quote(link.source)} -- {quote(link.target)} [label={quote(label)}];")
    rows.append("}")
    return "\n".join(rows)


st.markdown(
    """
    <div class="ns-hero">
      <div class="ns-eyebrow">Intent-driven network operations</div>
      <div class="ns-title">◈ NetState Reconciler</div>
      <div class="ns-sub">Discover the live network, compare it with desired configuration, detect drift, apply a minimal correction and verify the repaired state.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### CONTROL PLANE")
    endpoint = st.text_input("MCP HTTP endpoint", value=DEFAULT_ENDPOINT)
    st.caption("Packet Tracer MCP 0.10.2 default: 127.0.0.1:39400/mcp")
    st.caption(f"Build {__version__} · PID {os.getpid()} · Port {os.getenv('NETSTATE_PORT', '8501')}")
    engine = get_engine(endpoint.strip())
    if st.button("Connect & inspect MCP", type="primary"):
        with st.spinner("Connecting to MCP and discovering tool schemas..."):
            try:
                info = engine.connect()
                st.session_state.connected = True
                st.session_state.connection_info = info
                st.success(f"MCP reachable · {info['tool_count']} tools")
            except Exception as exc:
                st.session_state.connected = False
                st.error(str(exc))
    info = st.session_state.get("connection_info")
    if info:
        st.markdown("---")
        st.metric("Tools discovered", info.get("tool_count", 0))
        bridge = info.get("bridge_connected")
        if bridge is True:
            st.success("Packet Tracer bridge connected")
        elif bridge is False:
            st.error("Packet Tracer bridge is offline")
        else:
            st.warning("Bridge state not classified — inspect raw response")
        if info.get("bridge_result"):
            show_result("Bridge status response", info["bridge_result"])
    st.markdown("---")
    st.caption("Execution is disabled until MCP connection and live topology discovery succeed.")


tabs = st.tabs([
    "Overview",
    "Topology discovery",
    "Intent, mapping & configure",
    "Drift simulation",
    "Drift & reconciliation",
    "Diagnostics",
])

with tabs[0]:
    st.subheader("Live network operations")
    info = st.session_state.get("connection_info")
    inventory = st.session_state.get("inventory")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("MCP status", "Connected" if st.session_state.get("connected") else "Offline")
    c2.metric("Devices discovered", len(inventory.devices) if inventory else "—")
    c3.metric("Physical links", len(inventory.links) if inventory else "—")
    c4.metric("MCP tool count", info.get("tool_count", "—") if info else "—")
    st.info(
        "NetState can use the connected Packet Tracer MCP builder to plan and create a lab, then discover the actual device names, interfaces and links. "
        "If the installed MCP server does not expose a compatible build tool, the app will say so rather than pretending the topology was created."
    )
    st.markdown("#### Desired-state reconciliation workflow")
    st.markdown(
        "**01 Connect** → **02 Discover** → **03 Map devices** → **04 Save desired state** → "
        "**05 Analyze drift** → **06 Review minimal remediation** → **07 Apply & verify read-back**"
    )
    st.info(
        "The first automatic reconciliation slice focuses on named router ACL attachments. "
        "Other configuration families are not represented as compliant until their semantic parsers and verifiers are implemented."
    )

with tabs[1]:
    st.subheader("Create or discover a Packet Tracer topology")
    st.caption("Build a lab from the MCP builder, or inspect a topology that is already open. Names and interfaces are discovered after deployment; they are not required to be R1/SW1/PC-GUEST.")
    if not st.session_state.get("connected"):
        st.warning("Connect to MCP from the sidebar first.")
    else:
        build_tools = [name for name in ("pt_plan_topology", "pt_build_topology", "pt_deploy_topology", "pt_execute_topology_plan", "pt_apply_topology_plan", "pt_execute_plan", "pt_build_and_deploy_topology", "pt_run_topology", "pt_create_topology", "pt_live_deploy", "pt_full_build") if name in engine.toolbox.catalog]
        with st.container(border=True):
            st.markdown("#### Automatic lab builder")
            st.write("Choose the shape of the demo network. NetState will ask MCP to plan it, show the response, and only attempt deployment if a compatible deployment tool is available.")
            b1, b2, b3, b4 = st.columns(4)
            routers = b1.selectbox("Routers", [1, 2, 3], index=1)
            pcs_per_lan = b2.selectbox("PCs per LAN", [1, 2, 3, 4], index=1)
            switches_per_router = b3.selectbox("Switches per router", [1, 2], index=0)
            routing = b4.selectbox("Routing", ["Static", "OSPF", "RIP"], index=0)
            if not build_tools:
                st.warning("This MCP server does not advertise a recognized topology planning/build tool. Check Diagnostics → MCP Tools; the current server may only support discovery of a manually created topology.")
            if st.button("Plan automatic topology", type="primary", disabled="pt_plan_topology" not in engine.toolbox.catalog):
                try:
                    descriptor = engine.toolbox.catalog["pt_plan_topology"]
                    schema = descriptor.schema.get("properties", {}) or {}
                    semantic = {
                        "routers": routers,
                        "pcs_per_lan": pcs_per_lan,
                        "switches_per_router": switches_per_router,
                        "routing_protocol": routing.lower(),
                        "routing": routing.lower(),
                        "template": "multi_lan",
                    }
                    args = {}
                    for key, spec in schema.items():
                        norm = key.lower()
                        if key in semantic:
                            args[key] = semantic[key]
                        elif "router" in norm and "per" not in norm and "model" not in norm:
                            args[key] = routers
                        elif "pc" in norm and ("lan" in norm or "per" in norm):
                            args[key] = pcs_per_lan
                        elif "switch" in norm and ("router" in norm or "per" in norm):
                            args[key] = switches_per_router
                        elif "routing" in norm or "protocol" in norm:
                            enum = spec.get("enum") or []
                            value = routing.lower()
                            args[key] = next((v for v in enum if str(v).lower() == value), enum[0] if enum else value)
                        elif "template" in norm or "topology" in norm or "profile" in norm:
                            enum = spec.get("enum") or []
                            preferred = next((v for v in enum if "multi" in str(v).lower() or "lan" in str(v).lower()), None)
                            args[key] = preferred if preferred is not None else (enum[0] if enum else "multi_lan")
                        elif "model" in norm and spec.get("type") == "string":
                            args[key] = spec.get("default", "Cisco 2911" if "router" in norm else "Catalyst 2960-24TT")
                        elif "dhcp" in norm and spec.get("type") == "boolean":
                            args[key] = True
                        elif "include_wan" in norm or "wan" == norm:
                            args[key] = False
                        elif "floating" in norm or "backup" in norm:
                            args[key] = False
                        elif "default" in spec:
                            args[key] = spec["default"]
                        elif key in (descriptor.schema.get("required") or []):
                            if spec.get("type") == "integer": args[key] = 2
                            elif spec.get("type") == "boolean": args[key] = False
                            elif spec.get("enum"): args[key] = spec["enum"][0]
                            elif spec.get("type") == "string": args[key] = "multi_lan"
                    st.session_state.topology_plan_args = args
                    st.session_state.topology_plan_result = engine.toolbox.client.call_tool("pt_plan_topology", args)
                    st.session_state.topology_plan_tool = "pt_plan_topology"
                    st.success("Topology plan received. Review the plan response below before deployment.")
                except Exception as exc:
                    st.error(f"Could not plan topology: {exc}")
            if st.session_state.get("topology_plan_result"):
                plan_result = st.session_state.topology_plan_result
                st.markdown("**Plan summary**")
                plan_text = result_text(plan_result)
                st.info(plan_text[:2500] if plan_text else "MCP returned a structured plan. Expand technical details to inspect it.")
                with st.expander("Technical plan details"):
                    st.code(json.dumps(plan_result, indent=2, default=str)[:12000], language="json")
                deploy_candidates = ("pt_live_deploy", "pt_build_topology", "pt_deploy_topology", "pt_execute_topology_plan", "pt_apply_topology_plan", "pt_execute_plan", "pt_build_and_deploy_topology", "pt_run_topology", "pt_create_topology")
                deploy_tool = engine.toolbox.has(*deploy_candidates)
                if deploy_tool:
                    st.warning("Deployment changes the live Packet Tracer workspace. Save any lab you want to keep before proceeding.")
                    confirm_build = st.checkbox("I confirm this is the lab workspace NetState may create/modify.", key="confirm_auto_topology_deploy")
                    if st.button("Build & deploy topology", type="primary", disabled=not confirm_build):
                        try:
                            plan_payload = _extract_plan_payload(plan_result)
                            if plan_payload is None:
                                raise ValueError(
                                    "NetState could not isolate the structured topology plan from the MCP response. "
                                    "Deployment was stopped; inspect the raw plan response in Technical plan details."
                                )

                            # Packet Tracer MCP 0.10.1+ expects plan_path to reference a real
                            # .json file, not the serialized JSON string. Keep one file for both
                            # validation and deployment so both stages consume identical input.
                            plan_file_path = persist_topology_plan(
                                plan_payload, ROOT / ".netstate" / "plans"
                            )
                            st.caption(f"Persisted topology plan for MCP: {plan_file_path}")

                            # Follow the MCP server's recommended plan → validate → deploy flow.
                            validate_tool = engine.toolbox.has("pt_validate_plan")
                            if validate_tool:
                                validate_descriptor = engine.toolbox.catalog[validate_tool]
                                validate_args = _tool_plan_arguments(validate_descriptor, plan_payload, plan_file_path)
                                validation_result = engine.toolbox.client.call_tool(validate_tool, validate_args)
                                st.session_state.topology_validation_result = validation_result
                                if result_failed(validation_result):
                                    show_result("Topology validation rejected the plan", validation_result)
                                    raise ValueError("Packet Tracer MCP rejected the topology during validation. Nothing was deployed.")
                                validation_errors = _explicit_validation_errors(validation_result)
                                if validation_errors:
                                    show_result("Topology validation errors", validation_result)
                                    raise ValueError("Topology validation found errors: " + "; ".join(validation_errors))
                            else:
                                st.warning("This MCP server does not expose pt_validate_plan. Deployment cannot be validator-verified.")

                            desc = engine.toolbox.catalog[deploy_tool]
                            deploy_args = _tool_plan_arguments(desc, plan_payload, plan_file_path)
                            result = engine.toolbox.client.call_tool(deploy_tool, deploy_args)
                            st.session_state.topology_build_result = result
                            with st.expander("Live deployment response", expanded=True):
                                st.code(result_text(result) or json.dumps(result, indent=2, default=str), language="text")
                            if result_failed(result):
                                raise ValueError("Packet Tracer MCP reported a deployment failure. See the live deployment response above.")

                            st.info("The deploy tool returned without a recognised error. Checking the actual Packet Tracer canvas; this is not considered successful until devices are read back.")
                            inventory = None
                            last_discovery_error = None
                            # Give the Packet Tracer extension a few seconds to finish applying the topology.
                            for attempt in range(8):
                                try:
                                    inventory = engine.discover()
                                    break
                                except Exception as discovery_exc:
                                    last_discovery_error = discovery_exc
                                    if attempt < 7:
                                        time.sleep(1.0)
                            if inventory is None:
                                diagnostic = getattr(engine, "last_discovery_diagnostic", None)
                                with st.expander("Post-deployment read-back diagnostic", expanded=True):
                                    st.write(str(last_discovery_error))
                                    if diagnostic:
                                        st.json(diagnostic)
                                raise ValueError(
                                    "The deployment call returned, but no devices were confirmed in Packet Tracer. "
                                    "Treat this build as FAILED/UNVERIFIED; the workspace has not been proven to contain the planned topology."
                                )
                            st.session_state.inventory = inventory
                            st.success(f"Deployment verified from the live canvas: {len(inventory.devices)} devices, {len(inventory.links)} links.")
                        except Exception as exc:
                            st.error(f"Topology build/deploy failed or remains unverified: {exc}")
                else:
                    st.info("A planning tool is available, but no recognized deployment tool was found. NetState will not treat a plan as a deployed network. Check Diagnostics → MCP Tools for the server's actual build/execute tool name.")
        if st.button("Discover live topology", type="primary"):
            with st.spinner("Reading the live Packet Tracer workspace..."):
                try:
                    inventory = engine.discover()
                    st.session_state.inventory = inventory
                    st.success(f"Discovered {len(inventory.devices)} devices and {len(inventory.links)} links.")
                except Exception as exc:
                    st.error(str(exc))
                    diagnostic = getattr(engine, "last_discovery_diagnostic", None)
                    if diagnostic:
                        with st.expander("Topology discovery diagnostic (raw MCP responses)", expanded=True):
                            st.json(diagnostic)
        inventory = st.session_state.get("inventory")
        if inventory:
            left, right = st.columns([1.5, 1])
            with left:
                if inventory.links:
                    st.graphviz_chart(graph_dot(inventory), use_container_width=True)
                else:
                    st.info("No link records were parsed. Inspect the raw topology response.")
            with right:
                st.markdown("#### Device inventory")
                st.dataframe(
                    [
                        {"Device": item.name, "Model": item.model, "Category": item.category,
                         "Interfaces": ", ".join(item.interfaces), "IP addresses": ", ".join(item.ip_addresses)}
                        for item in inventory.devices
                    ], use_container_width=True, hide_index=True,
                )
                st.markdown("#### Physical links")
                st.dataframe(
                    [
                        {"Endpoint A": f"{link.source} {link.source_port}",
                         "Endpoint B": f"{link.target} {link.target_port}", "Cable": link.cable}
                        for link in inventory.links
                    ], use_container_width=True, hide_index=True,
                )
            with st.expander("Raw MCP topology response"):
                st.json(inventory.raw)

with tabs[2]:
    st.subheader("Declare the network's desired state")
    st.caption("Declare desired network roles using logical names; bind those roles to discovered Packet Tracer devices and interfaces below.")
    profiles = {
        "Secure intent (guest-to-finance ACL enabled)": ROOT / "config" / "intent.example.yaml",
        "Attack demo baseline (intentionally permissive)": ROOT / "config" / "intent.attack-demo-baseline.yaml",
    }
    selected_profile = st.selectbox("Load a configuration profile", list(profiles))
    if st.session_state.get("intent_profile_loaded") != selected_profile:
        profile_path = profiles[selected_profile]
        st.session_state["intent_editor"] = profile_path.read_text(encoding="utf-8") if profile_path.exists() else "routers: {}\n"
        st.session_state.intent_profile_loaded = selected_profile
    yaml_text = st.text_area("Network intent (YAML)", height=470, key="intent_editor")
    st.session_state.intent_yaml = yaml_text
    try:
        intent = load_intent(yaml_text)
        st.success(f"Intent valid · {len(intent.routers)} routers · {len(intent.switches)} switches · {len(intent.hosts)} hosts")
        inventory = st.session_state.get("inventory")
        if inventory:
            effective_intent, mapping_problems, _ = render_device_interface_mapping(intent, inventory)
        else:
            effective_intent = None
            mapping_problems = ["Live topology has not been discovered."]
            st.warning("Discover the live topology before binding logical device roles and interfaces.")

        if effective_intent is not None:
            st.session_state["effective_intent_json"] = effective_intent.model_dump(mode="json")
        else:
            st.session_state.pop("effective_intent_json", None)

        intent_for_compile = effective_intent or intent
        security_on = st.checkbox("Include SSH management hardening for routers", value=False)
        if security_on:
            st.warning(
                "Packet Tracer commonly requires interactive RSA generation. NetState will not send the "
                "unsupported inline `crypto key generate rsa modulus 1024` form. After applying the SSH settings, "
                "settings, generate keys manually on each router with `crypto key generate rsa` and answer "
                "the modulus prompt (for example, 1024 bits) before expecting SSH login to work."
            )
        secret_values: dict[str, str] = {}
        if security_on:
            secret_values["username"] = st.text_input("Local management username", value="netadmin")
            secret_values["user_secret"] = st.text_input("Local user secret (not saved to YAML or reports)", type="password")
            secret_values["enable_secret"] = st.text_input("Enable secret (optional; not saved)", type="password")
        configs = compile_intent(intent_for_compile, secret_values if security_on else None)
        with st.expander("Generated IOS command plan", expanded=True):
            if effective_intent is None:
                st.caption("Preview uses logical names only. Applying is disabled until mappings validate.")
            else:
                st.caption("Command targets and interfaces have been resolved to the discovered Packet Tracer inventory.")
            for config in configs:
                st.markdown(f"**{config.device} · {config.role} · {len(config.commands)} commands**")
                preview = ["<redacted secret command>" if " secret " in line else line for line in config.commands]
                st.code("\n".join(preview), language="text")

        problems = list(mapping_problems)
        if inventory and effective_intent is not None:
            inventory_problems = validate_intent_against_inventory(effective_intent, inventory)
            problems.extend(inventory_problems)
            if not problems:
                st.success("Mapped intent matches discovered devices, interface names and inventory roles.")
        elif not inventory:
            st.warning("Live topology has not been discovered.")

        st.markdown("#### Execution safeguards")
        approved = st.checkbox("I reviewed the generated commands and approve applying them to the live Packet Tracer devices.")
        no_checkpoint = st.checkbox("Proceed if one or more device configuration checkpoints are unavailable (I accept manual recovery).", value=False)
        connection_info = st.session_state.get("connection_info") or {}
        bridge_ready = connection_info.get("bridge_connected") is True
        if st.session_state.get("connected") and not bridge_ready:
            st.warning("MCP HTTP is reachable, but the Packet Tracer bridge has not been positively confirmed. Live configuration remains blocked.")
        can_apply = (
            st.session_state.get("connected") and bridge_ready
            and inventory is not None and effective_intent is not None
            and not problems and approved
        )
        if st.button("Apply approved configuration", type="primary", disabled=not can_apply):
            with st.spinner("Creating checkpoints and configuring devices. Do not close Packet Tracer."):
                try:
                    report = engine.apply_intent(effective_intent, approved=True, allow_without_checkpoint=no_checkpoint, security=secret_values if security_on else None)
                    st.session_state.last_report = report
                    if report.status == "BLOCKED":
                        st.error("Execution blocked before device changes.")
                    elif report.status == "PARTIAL_FAILURE":
                        st.error("Execution stopped after a device command failed. The network may be partially configured.")
                    else:
                        st.success("Configuration commands submitted. Live verification is still required.")
                    st.json({
                        "transaction_id": report.transaction_id,
                        "status": report.status,
                        "steps": [step.__dict__ for step in report.steps],
                        "errors": report.errors,
                        "checkpoints": report.checkpoint_files,
                        "note": report.note,
                    })
                except Exception as exc:
                    st.error(str(exc))
    except (IntentError, CompileError) as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Intent error: {exc}")

with tabs[3]:
    st.subheader("Controlled drift simulation")
    st.caption(
        "Introduce one intentional, reversible configuration deviation in the Packet Tracer lab. "
        "This is fault injection for a configuration-drift demonstration, not an exploit."
    )
    if not st.session_state.get("connected") or st.session_state.get("inventory") is None:
        st.warning("Connect to MCP and discover the live topology first.")
    else:
        try:
            demo_intent = engine.store.load_desired_intent()
        except Exception as exc:
            demo_intent = None
            st.error(f"Could not load the saved desired state: {exc}")
        if demo_intent is None:
            st.info("First map the logical devices/interfaces in Intent, mapping & configure, then save the desired state in Drift & reconciliation. Simulation is disabled until a desired-state baseline exists.")
        else:
            acl_choices = [
                (device, acl.name, acl.interface, acl.direction)
                for device, router in demo_intent.routers.items()
                for acl in router.acls
            ]
            if not acl_choices:
                st.warning("The current mapped intent contains no named router ACLs to use for controlled drift simulation.")
            else:
                labels = [f"{device} · {acl} · {interface} ({direction})" for device, acl, interface, direction in acl_choices]
                selected_index = st.selectbox("Select the intended policy attachment to disturb", range(len(labels)), format_func=lambda i: labels[i])
                selected_device, selected_acl, selected_interface, selected_direction = acl_choices[selected_index]
                st.markdown("#### What this simulation changes")
                st.info(
                    f"NetState will remove only `{selected_acl}` from `{selected_device}/{selected_interface}` "
                    f"({selected_direction}). The ACL definition and all other interfaces/configuration are left untouched. "
                    "The drift detector should then report the missing attachment; reconciliation should restore it."
                )
                st.warning("Save your Packet Tracer project before fault injection. This changes the live lab configuration.")
                approve_drift = st.checkbox("I approve removing this ACL attachment from the live lab.", key="approve_acl_drift_sim")
                allow_no_checkpoint = st.checkbox(
                    "Proceed if pt_backup_config is unavailable (I have saved a separate .pkt copy).",
                    value=False, key="allow_acl_drift_without_checkpoint",
                )
                if st.button("Simulate ACL attachment drift", type="primary", disabled=not approve_drift):
                    try:
                        with st.spinner("Checking the current ACL attachment, checkpointing, and introducing one controlled change..."):
                            result = engine.simulate_acl_attachment_drift(
                                demo_intent, selected_device, selected_acl,
                                approved=True, allow_without_checkpoint=allow_no_checkpoint,
                            )
                        st.session_state["last_drift_simulation"] = result
                        if result.get("status") == "DRIFT_INJECTED":
                            st.success("Controlled drift introduced and confirmed by running-config read-back.")
                        elif result.get("status") == "APPLIED_UNVERIFIED":
                            st.warning("Change was submitted, but read-back could not verify it.")
                        else:
                            st.error(f"Simulation did not complete cleanly: {result.get('status')}")
                        st.json({k: v for k, v in result.items() if k != "raw_config"})
                    except Exception as exc:
                        st.error(f"Drift simulation blocked or failed: {exc}")
                last_sim = st.session_state.get("last_drift_simulation")
                if last_sim:
                    st.markdown("#### Last simulation")
                    st.write(
                        f"{last_sim.get('device', '?')} / {last_sim.get('interface', '?')}: "
                        f"`{last_sim.get('before', '?')}` → `{last_sim.get('after', '?')}` · "
                        f"**{last_sim.get('status', 'UNKNOWN')}**"
                    )
                    st.caption("Next: open Drift & reconciliation and run Analyze live configuration drift.")

        st.divider()
        st.markdown("#### Optional reachability evidence")
        inventory = st.session_state.inventory
        likely_hosts = [d.name for d in inventory.devices if d.category == "host" or "pc" in (d.model + " " + d.category).lower() or "laptop" in d.model.lower()]
        source_options = likely_hosts or [d.name for d in inventory.devices]
        left, right = st.columns([1, 1])
        with left:
            probe_source = st.selectbox("Probe source", source_options, key="drift_probe_source")
            probe_target = st.text_input("Destination IPv4 address", value="10.10.30.10", key="drift_probe_target")
            if st.button("Run ICMP probe", disabled=not bool(probe_target.strip())):
                try:
                    assessment = engine.verify_connectivity(probe_source, probe_target.strip())
                    st.session_state["drift_probe_result"] = {
                        "status": assessment.status, "summary": assessment.summary,
                        "evidence": assessment.evidence, "policy_evidence": assessment.policy_evidence,
                    }
                except Exception as exc:
                    st.error(f"Probe failed: {exc}")
        with right:
            probe_result = st.session_state.get("drift_probe_result")
            if probe_result:
                status = probe_result["status"]
                if status in {"REACHABLE", "BLOCKED_BY_POLICY"}:
                    st.success(f"{status} · {probe_result['summary']}")
                elif status == "NO_CONNECTIVITY":
                    st.warning(f"{status} · cause unconfirmed")
                else:
                    st.info(f"{status} · {probe_result['summary']}")
                with st.expander("Probe evidence"):
                    st.code(probe_result.get("evidence", ""), language="text")

with tabs[4]:
    st.subheader("Drift detection & reconciliation")
    st.caption(
        "Compare the mapped desired intent with live router running-config. This release automatically "
        "detects and repairs named ACL attachment drift; other configuration families remain read-only/manual-review."
    )
    if not st.session_state.get("connected") or st.session_state.get("inventory") is None:
        st.warning("Connect to MCP and discover the live topology first.")
    else:
        intent_payload = st.session_state.get("effective_intent_json")
        current_intent = None
        if intent_payload:
            try:
                current_intent = NetworkIntent.model_validate(intent_payload)
            except Exception as exc:
                st.error(f"Mapped desired intent is invalid: {exc}")
        if current_intent is None:
            try:
                current_intent = engine.store.load_desired_intent()
            except Exception as exc:
                st.error(f"Could not load saved desired state: {exc}")

        if current_intent is None:
            st.warning("Open Intent, mapping & configure, complete device/interface mapping, then return here.")
        else:
            expected_acl_count = sum(len(router.acls) for router in current_intent.routers.values())
            m1, m2 = st.columns(2)
            m1.metric("Mapped routers", len(current_intent.routers))
            m2.metric("Desired ACL attachments", expected_acl_count)
            if st.button("Save mapped intent as desired state", type="primary"):
                try:
                    path = engine.store.save_desired_intent(current_intent)
                    st.session_state["desired_state_saved"] = True
                    st.success(f"Desired state saved: {path}")
                except Exception as exc:
                    st.error(f"Could not save desired state: {exc}")

            desired_path = engine.store.snapshots / "desired-state.json"
            if desired_path.exists():
                st.caption(f"Saved desired state: `{desired_path}`")

            if st.button("Analyze live configuration drift"):
                try:
                    with st.spinner("Reading live router configurations and comparing ACL attachments with desired intent..."):
                        analysis = engine.analyze_intent_drift(current_intent)
                    st.session_state["last_intent_drift_analysis"] = analysis
                except Exception as exc:
                    st.session_state.pop("last_intent_drift_analysis", None)
                    st.error(f"Drift analysis failed; no compliance result was produced: {exc}")

            analysis = st.session_state.get("last_intent_drift_analysis")
            if analysis:
                findings = analysis.get("findings", [])
                st.markdown("#### Analysis result")
                st.caption(f"Scope: {analysis.get('scope')} · Devices read: {analysis.get('devices_audited', 0)}")
                if not findings:
                    st.success("COMPLIANT — all named ACL attachments in the supported intent scope match the live running-config.")
                else:
                    st.warning(f"{len(findings)} drift/coverage finding(s) detected.")
                    rows = [{
                        "Device": f.get("device"), "Finding": f.get("code"),
                        "Severity": f.get("severity"), "Object": f.get("object_name"),
                        "Expected": f.get("expected"), "Observed": f.get("observed"),
                        "Automatic repair": "Available" if f.get("auto_remediable") else "Manual review",
                    } for f in findings]
                    st.dataframe(rows, use_container_width=True, hide_index=True)
                    for finding in findings:
                        with st.expander(f"{finding['device']} · {finding['code']} · {finding['object_name']}"):
                            st.write(finding.get("explanation", ""))
                            if finding.get("remediation_commands"):
                                st.code("\n".join(finding["remediation_commands"]), language="text")

                    repairable = [f for f in findings if f.get("auto_remediable")]
                    unsupported = [f for f in findings if not f.get("auto_remediable")]
                    if repairable:
                        st.markdown("#### Minimal remediation plan")
                        st.write("Only the missing/wrong ACL attachment is changed. NetState does not regenerate router interfaces, DHCP, OSPF, VLANs or unrelated ACL rules.")
                        st.code("\n\n".join(
                            f"! {f['device']}\n" + "\n".join(f["remediation_commands"])
                            for f in repairable
                        ), language="cisco_ios")
                        if unsupported:
                            st.warning("Some findings are not eligible for automatic remediation. They will not be changed by this transaction.")
                        approve_repair = st.checkbox("I reviewed and approve this minimal ACL remediation.", key="approve_acl_reconciliation")
                        allow_no_checkpoint_repair = st.checkbox(
                            "Proceed without an MCP device checkpoint (I saved a separate .pkt backup).",
                            value=False, key="allow_acl_reconcile_without_checkpoint",
                        )
                        if st.button("Apply approved ACL remediation & verify", type="primary", disabled=not approve_repair):
                            try:
                                with st.spinner("Checkpointing affected devices, applying only ACL attachment corrections, and reading back live configuration..."):
                                    result = engine.remediate_acl_drift(
                                        current_intent, approved=True,
                                        allow_without_checkpoint=allow_no_checkpoint_repair,
                                    )
                                st.session_state["last_acl_remediation"] = result
                                if result.get("status") == "VERIFIED":
                                    st.success("REMEDIATION VERIFIED — live running-config now matches the desired ACL attachment state.")
                                elif result.get("status") == "NO_DRIFT":
                                    st.success("No ACL attachment drift remains. No commands were sent.")
                                elif result.get("status") == "BLOCKED":
                                    st.error(f"Remediation blocked: {result.get('reason')}")
                                else:
                                    st.warning(f"Remediation status: {result.get('status')} — inspect per-device steps and read-back evidence.")
                                st.json(result)
                            except Exception as exc:
                                st.error(f"Remediation could not be completed: {exc}")
                    elif unsupported:
                        st.info("No safe automatic ACL repair is available for these findings. Review the evidence and make the required change manually.")

            previous_remediation = st.session_state.get("last_acl_remediation")
            if previous_remediation:
                st.markdown("#### Last remediation transaction")
                st.write(f"Transaction `{previous_remediation.get('transaction_id')}` · **{previous_remediation.get('status')}**")

        with st.expander("Advanced: topology and raw running-config snapshots"):
            inventory = st.session_state.get("inventory")
            if inventory and st.button("Save current topology as baseline"):
                baseline_path = engine.store.save_topology_baseline(inventory)
                st.session_state.baseline = inventory.to_dict()
                st.success(f"Topology baseline saved: {baseline_path}")
            if st.session_state.get("baseline") is None:
                st.session_state.baseline = engine.store.load_topology_baseline()
            if inventory and st.session_state.get("baseline") and st.button("Compare topology with baseline"):
                drifts = compare_topology(st.session_state.baseline, inventory)
                if drifts:
                    st.dataframe([drift.__dict__ for drift in drifts], use_container_width=True, hide_index=True)
                else:
                    st.success("No topology-level drift detected.")
            if current_intent:
                raw_devices = list(current_intent.routers) + list(current_intent.switches)
                if st.button("Capture redacted running-config baseline"):
                    try:
                        captured = engine.capture_config_baseline(raw_devices)
                        st.success(f"Captured {len(captured)} device configurations.")
                    except Exception as exc:
                        st.error(str(exc))
                if st.button("Compare raw running-config with baseline"):
                    try:
                        diffs = engine.compare_config_baseline(raw_devices)
                        if diffs:
                            for name, diff_text in diffs.items():
                                with st.expander(name):
                                    st.code(diff_text, language="diff")
                        else:
                            st.success("No textual running-config changes detected against the raw baseline.")
                    except Exception as exc:
                        st.error(str(exc))
            left, right = st.columns(2)
            with left:
                if st.button("Run Packet Tracer health check"):
                    try:
                        health = engine.health_check()
                        st.json(health)
                    except Exception as exc:
                        st.error(str(exc))
            with right:
                filename = st.text_input("Packet Tracer project filename", value="NetState-Lab.pkt")
                if st.button("Save live .pkt project"):
                    try:
                        saved = engine.save_project(filename)
                        st.json(saved)
                    except Exception as exc:
                        st.error(str(exc))

with tabs[5]:
    st.subheader("MCP capability and diagnostic view")
    st.info(f"Running NetState Reconciler {__version__} · PID {os.getpid()} · project root `{ROOT}` · port {os.getenv('NETSTATE_PORT', '8501')}")
    info = st.session_state.get("connection_info")
    if getattr(engine, "last_discovery_diagnostic", None):
        with st.expander("Latest topology discovery diagnostic", expanded=True):
            st.json(engine.last_discovery_diagnostic)
    if info:
        st.markdown("#### Required tool availability")
        catalog = set(info.get("tool_names", []))
        groups = {
            "Discovery": ["pt_bridge_status", "pt_query_topology", "pt_export_topology"],
            "Configuration": ["pt_cli", "pt_host_ip_config", "pt_apply_vlan", "pt_apply_acl"],
            "Verification": ["pt_verify_connectivity", "pt_health_check", "pt_diff"],
            "Security": ["pt_audit_security", "pt_simulation_mode", "pt_simulation_step", "pt_read_packet_trace"],
            "Persistence": ["pt_backup_config", "pt_save_project"],
        }
        for group, names in groups.items():
            st.markdown(f"**{group}**")
            st.dataframe([{"Tool": name, "Available": "YES" if name in catalog else "NO"} for name in names], hide_index=True, use_container_width=True)
        if st.button("Refresh MCP tool catalog"):
            try:
                refreshed = engine.connect()
                st.session_state.connection_info = refreshed
                st.success(f"Refreshed: {refreshed['tool_count']} tools discovered.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        with st.expander("All discovered tool schemas"):
            st.json({name: descriptor.schema for name, descriptor in engine.toolbox.catalog.items()})
    else:
        st.info("Connect to MCP to inspect the runtime tool catalog.")
    st.markdown("#### Application logs")
    log_dir = ROOT / ".netstate" / "reports"
    reports = sorted(log_dir.glob("*.json"), reverse=True) if log_dir.exists() else []
    if reports:
        selected = st.selectbox("Execution report", reports, format_func=lambda path: path.name)
        st.json(json.loads(selected.read_text(encoding="utf-8")))
    else:
        st.caption("No execution reports have been recorded yet.")

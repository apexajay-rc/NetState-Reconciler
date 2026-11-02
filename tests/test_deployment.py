import json
from pathlib import Path

import pytest

from netstate_reconciler.deployment import persist_topology_plan, tool_plan_arguments
from netstate_reconciler.mcp_client import ToolDescriptor


def test_persist_topology_plan_writes_valid_json_file(tmp_path: Path):
    payload = {
        "devices": [{"name": "R1", "model": "Cisco 2911"}],
        "links": [],
        "errors": [],
    }

    plan_path = persist_topology_plan(payload, tmp_path / "plans")

    assert plan_path.is_absolute()
    assert plan_path.suffix == ".json"
    assert plan_path.exists()
    assert json.loads(plan_path.read_text(encoding="utf-8")) == payload


def test_plan_path_schema_receives_filename_not_json_document(tmp_path: Path):
    payload = {"devices": [{"name": "R1"}], "links": []}
    plan_path = persist_topology_plan(payload, tmp_path)
    descriptor = ToolDescriptor(
        name="pt_validate_plan",
        description="Validate a plan",
        schema={
            "type": "object",
            "properties": {"plan_path": {"type": "string"}},
            "required": ["plan_path"],
        },
    )

    arguments = tool_plan_arguments(descriptor, payload, plan_path)

    assert arguments == {"plan_path": str(plan_path)}
    assert arguments["plan_path"].endswith(".json")
    assert json.loads(Path(arguments["plan_path"]).read_text()) == payload


def test_plan_json_schema_receives_serialized_json(tmp_path: Path):
    payload = {"devices": [], "links": []}
    plan_path = persist_topology_plan(payload, tmp_path)
    descriptor = ToolDescriptor(
        name="some_tool",
        description="",
        schema={
            "type": "object",
            "properties": {"plan_json": {"type": "string"}},
            "required": ["plan_json"],
        },
    )

    arguments = tool_plan_arguments(descriptor, payload, plan_path)

    assert json.loads(arguments["plan_json"]) == payload


def test_required_unknown_argument_is_rejected(tmp_path: Path):
    plan_path = persist_topology_plan({}, tmp_path)
    descriptor = ToolDescriptor(
        name="some_tool",
        description="",
        schema={
            "type": "object",
            "properties": {
                "plan_path": {"type": "string"},
                "device_name": {"type": "string"},
            },
            "required": ["plan_path", "device_name"],
        },
    )

    with pytest.raises(ValueError, match="device_name"):
        tool_plan_arguments(descriptor, {}, plan_path)

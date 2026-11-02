"""Helpers for safely handing topology plans to Packet Tracer MCP tools."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def persist_topology_plan(plan_payload: object, directory: Path) -> Path:
    """Write a topology plan to a stable JSON file readable by the local MCP server.

    Packet Tracer MCP 0.10.1+ accepts ``plan_path`` for validation and live
    deployment. It does not accept the serialized JSON document in that field.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = (directory / f"topology-plan-{uuid.uuid4().hex}.json").resolve()
    temporary = target.with_suffix(".json.tmp")
    serialized = json.dumps(plan_payload, indent=2, ensure_ascii=False, default=str)
    temporary.write_text(serialized + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def tool_plan_arguments(
    descriptor: object,
    plan_payload: object,
    plan_file_path: Path,
) -> dict[str, Any]:
    """Map a plan to an MCP tool's schema, distinguishing paths from JSON text."""
    schema = getattr(descriptor, "schema", {}) or {}
    properties = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    args: dict[str, Any] = {}

    for key, spec in properties.items():
        normalized = str(key).lower()
        description = str(spec.get("description", "")).lower()
        is_plan_path = (
            ("plan" in normalized and "path" in normalized)
            or ("plan" in normalized and "file" in normalized and "path" in description)
            or ("plan" in description and "path to" in description and "json" in description)
        )
        is_plan_content = "plan" in normalized and "id" not in normalized and not is_plan_path

        if is_plan_path:
            # The server validates the extension and reads this file itself.
            args[key] = str(plan_file_path.resolve())
        elif is_plan_content:
            field_type = spec.get("type")
            if field_type == "string":
                args[key] = json.dumps(plan_payload, separators=(",", ":"), default=str)
            elif field_type in ("object", "array", None):
                args[key] = plan_payload
            else:
                raise ValueError(f"Unsupported type `{field_type}` for MCP plan argument `{key}`.")
        elif "default" in spec:
            args[key] = spec["default"]
        elif key in required:
            raise ValueError(
                f"MCP tool requires `{key}`, which NetState cannot infer safely from the plan. "
                "Inspect the runtime schema before deploying."
            )

    missing = required - set(args)
    if missing:
        raise ValueError(f"Missing required MCP arguments: {', '.join(sorted(missing))}")

    return args

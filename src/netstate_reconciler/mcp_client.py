from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Callable


class MCPConnectionError(RuntimeError):
    pass


class MCPToolError(RuntimeError):
    pass


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items() if not key.startswith("_")}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def normalize_mcp_result(result: Any) -> dict[str, Any]:
    """Preserve structured MCP content and also expose readable text."""
    data = _plain(result)
    if not isinstance(data, dict):
        data = {"value": data}
    content = data.get("content") or []
    texts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("text") is not None:
            texts.append(str(item["text"]))
        elif isinstance(item, str):
            texts.append(item)
    structured = data.get("structuredContent", data.get("structured_content"))
    parsed: list[Any] = []
    for text in texts:
        try:
            parsed.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "isError": bool(data.get("isError", data.get("is_error", False))),
        "structured": structured,
        "content": content,
        "text": "\n".join(texts),
        "parsed_text": parsed,
        "raw": data,
    }


def result_text(result: Any) -> str:
    normalized = result if isinstance(result, dict) and "raw" in result else normalize_mcp_result(result)
    pieces = [normalized.get("text", "")]
    structured = normalized.get("structured")
    if structured is not None:
        pieces.append(json.dumps(structured, default=str))
    if not pieces[0] and normalized.get("raw"):
        pieces.append(json.dumps(normalized["raw"], default=str))
    return "\n".join(piece for piece in pieces if piece)


def result_failed(result: Any) -> bool:
    normalized = result if isinstance(result, dict) and "raw" in result else normalize_mcp_result(result)
    if normalized.get("isError"):
        return True
    text = result_text(normalized).lower()
    markers = (
        "unknown command",
        "invalid input detected",
        "waiting for an answer",
        "command timed out",
        "timed out waiting",
        "timeout",
        "% invalid input",
        "invalid command",
        "tool execution failed",
        "validation failed",
        "error executing",
    )
    return any(marker in text for marker in markers) or bool(
        re.search(r"\bERROR\b|\bFAILED\b|\bfailed\s*:", text, re.IGNORECASE)
    )


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    schema: dict[str, Any]


class MCPHTTPClient:
    """Small synchronous facade over the official Python MCP streamable-HTTP client."""

    def __init__(self, endpoint: str = "http://127.0.0.1:39400/mcp", timeout: float = 45.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def _run(self, factory: Callable[[], Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(factory())
        raise MCPConnectionError(
            "An asyncio event loop is already running. Call this client from Streamlit's synchronous script context."
        )

    async def _with_session(self, operation: Callable[[Any], Any]) -> Any:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:
            raise MCPConnectionError(
                "The MCP SDK is not installed in this environment. Install the project with `pip install -e .`."
            ) from exc

        try:
            async with streamablehttp_client(self.endpoint) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await asyncio.wait_for(session.initialize(), timeout=self.timeout)
                    return await operation(session)
        except Exception as exc:
            if isinstance(exc, (MCPConnectionError, MCPToolError)):
                raise
            raise MCPConnectionError(f"Could not communicate with MCP endpoint {self.endpoint}: {exc}") from exc

    def list_tools(self) -> list[ToolDescriptor]:
        async def operation(session: Any) -> list[ToolDescriptor]:
            response = await asyncio.wait_for(session.list_tools(), timeout=self.timeout)
            descriptors: list[ToolDescriptor] = []
            for tool in response.tools:
                schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
                descriptors.append(
                    ToolDescriptor(
                        name=str(getattr(tool, "name", "")),
                        description=str(getattr(tool, "description", "") or ""),
                        schema=_plain(schema) if isinstance(_plain(schema), dict) else {},
                    )
                )
            return descriptors

        return self._run(lambda: self._with_session(operation))

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async def operation(session: Any) -> dict[str, Any]:
            response = await asyncio.wait_for(
                session.call_tool(name, arguments=arguments or {}), timeout=self.timeout
            )
            return normalize_mcp_result(response)

        return self._run(lambda: self._with_session(operation))


ALIASES: dict[str, tuple[str, ...]] = {
    "device": ("device", "device_name", "name", "hostname", "from_device", "source_device"),
    "from_device": ("from_device", "source_device", "device", "device_name", "source"),
    "to_ip": ("to_ip", "destination_ip", "target_ip", "ip", "address"),
    "command": ("command", "cmd", "cli_command", "input", "text"),
    "commands": ("commands", "lines", "command_list", "cli_commands"),
    "mode": ("mode", "configuration_mode", "ip_mode", "method", "simulation_mode"),
    "step": ("step", "direction", "action", "operation"),
    "ip_address": ("ip_address", "ip", "address"),
    "subnet_mask": ("subnet_mask", "mask", "netmask"),
    "gateway": ("gateway", "default_gateway", "default_router"),
    "dns": ("dns", "dns_server", "dns_address"),
    "filename": ("filename", "file_name", "path", "project_path"),
    "include_xml": ("include_xml",),
    "timeout": ("timeout", "timeout_seconds", "timeout_s"),
}


class MCPToolbox:
    """Runtime tool catalog and schema-aware semantic argument mapping."""

    def __init__(self, client: MCPHTTPClient):
        self.client = client
        self.catalog: dict[str, ToolDescriptor] = {}

    def refresh(self) -> list[ToolDescriptor]:
        tools = self.client.list_tools()
        self.catalog = {tool.name: tool for tool in tools if tool.name}
        return tools

    def has(self, *names: str) -> str | None:
        return next((name for name in names if name in self.catalog), None)

    def invoke(self, tool_name: str, semantic: dict[str, Any] | None = None) -> dict[str, Any]:
        if tool_name not in self.catalog:
            self.refresh()
        descriptor = self.catalog.get(tool_name)
        if descriptor is None:
            raise MCPToolError(f"MCP tool `{tool_name}` is not available in the connected server.")
        semantic = semantic or {}
        properties = descriptor.schema.get("properties", {}) or {}
        required = descriptor.schema.get("required", []) or []
        mapped: dict[str, Any] = {}
        for property_name, property_schema in properties.items():
            aliases = {property_name}
            for semantic_name, value in semantic.items():
                names = ALIASES.get(semantic_name, (semantic_name,))
                if property_name in names:
                    mapped[property_name] = value
                    aliases.add(property_name)
                    break
            if property_name in semantic:
                mapped[property_name] = semantic[property_name]
        missing = [field for field in required if field not in mapped]
        if missing:
            raise MCPToolError(
                f"Cannot safely call `{tool_name}`: this installed tool requires unsupported arguments: "
                f"{', '.join(missing)}. Inspect its schema in the MCP Tools page."
            )
        return self.client.call_tool(tool_name, mapped)

    def invoke_first(self, candidates: tuple[str, ...], semantic: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        tool_name = self.has(*candidates)
        if not tool_name:
            raise MCPToolError(f"None of these tools is available: {', '.join(candidates)}")
        return tool_name, self.invoke(tool_name, semantic)

    def cli(self, device: str, commands: list[str]) -> list[dict[str, Any]]:
        """Execute a command batch when supported, otherwise issue commands sequentially."""
        tool_name = self.has("pt_cli", "pt_run_cli_bulk", "pt_run_cli")
        if not tool_name:
            raise MCPToolError("The connected MCP server exposes no supported device CLI tool.")
        descriptor = self.catalog[tool_name]
        properties = descriptor.schema.get("properties", {}) or {}
        command_field = next((key for key in ALIASES["commands"] if key in properties), None)
        if command_field:
            field_schema = properties.get(command_field, {}) or {}
            batch_value: Any = commands if field_schema.get("type") == "array" else "\n".join(commands)
            result = self.invoke(tool_name, {"device": device, "commands": batch_value})
            return [result]
        results: list[dict[str, Any]] = []
        for command in commands:
            results.append(self.invoke(tool_name, {"device": device, "command": command}))
            if result_failed(results[-1]):
                break
        return results

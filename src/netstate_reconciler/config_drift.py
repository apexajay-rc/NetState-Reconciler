from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .mcp_client import result_failed, result_text


SECRET_LINE_PATTERNS = (
    re.compile(r"^\s*(enable|username|password|secret|snmp-server community|tacacs-server key|radius-server key)\b", re.I),
    re.compile(r"\b(key-string|pre-shared-key|authentication-key)\b", re.I),
)


def redact_config(text: str) -> str:
    """Remove credential-bearing directives before a config snapshot is persisted."""
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(pattern.search(stripped) for pattern in SECRET_LINE_PATTERNS):
            cleaned.append("<credential directive redacted>")
        elif stripped.startswith("Building configuration") or stripped.startswith("Current configuration"):
            continue
        elif stripped.startswith("!") and any(
            marker in stripped.lower() for marker in ("last configuration change", "nvram config last updated")
        ):
            continue
        else:
            cleaned.append(line.rstrip())
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return "\n".join(cleaned) + ("\n" if cleaned else "")


def redact_output(text: str) -> str:
    """Redact credential directives even when the MCP response includes a device prompt."""
    cleaned = []
    for line in text.splitlines():
        if re.search(r"\b(enable secret|enable password|username \S+.*\b(secret|password)|password \S+|snmp-server community|tacacs-server key|radius-server key|crypto isakmp key|pre-shared-key|key-string)\b", line, re.I):
            cleaned.append("<credential-bearing output redacted>")
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


def config_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_diff(before: str, after: str, device: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(),
            fromfile=f"baseline/{device}", tofile=f"current/{device}", lineterm="",
        )
    )


def classify_capture(result: Any, device: str) -> tuple[str, str]:
    if result_failed(result):
        raise RuntimeError(f"Could not read running configuration from {device}: {result_text(result)}")
    raw = result_text(result)
    if isinstance(result, dict):
        structured = result.get("structured")
        if isinstance(structured, dict):
            for key in ("running_config", "config", "output", "text", "result"):
                candidate = structured.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    raw = candidate
                    break
    if not raw.strip():
        raise RuntimeError(f"The CLI tool returned no running configuration for {device}.")
    redacted = redact_config(raw)
    if len(redacted.splitlines()) < 2:
        raise RuntimeError(
            f"The response for {device} did not look like a running configuration. "
            "Inspect the MCP tool response before creating a baseline."
        )
    return redacted, config_digest(redacted)

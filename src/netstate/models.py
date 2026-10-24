"""Typed models for parsed configurations, drift findings, and remediation plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass(slots=True)
class Drift:
    path: str
    desired: Any
    actual: Any
    severity: Severity
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RemediationAction:
    path: str
    summary: str
    commands: list[str] = field(default_factory=list)
    severity: Severity = "MEDIUM"
    auto_applicable: bool = False
    requires_approval: bool = True
    manual_review_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditReport:
    device: str
    compliant: bool
    desired_file: str
    source: str
    drifts: list[Drift]
    parser_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "compliant": self.compliant,
            "audit_incomplete": bool(self.parser_warnings),
            "desired_file": self.desired_file,
            "source": self.source,
            "drift_count": len(self.drifts),
            "drifts": [d.to_dict() for d in self.drifts],
            "parser_warnings": self.parser_warnings,
        }

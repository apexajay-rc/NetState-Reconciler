"""Conservative remediation transaction primitives.

The module provides a driver-agnostic transaction boundary. Device-specific execution must
be implemented and integration-tested by an adapter before enabling writes in a real lab.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

@dataclass(frozen=True)
class DeviceCapabilities:
    supports_checkpoint: bool = False
    supports_rollback: bool = False
    supported_commands: tuple[str, ...] = ()
    allow_interface_address_changes: bool = False
    allow_acl_changes: bool = False

    def permits(self, command: str) -> bool:
        return any(command == prefix or command.startswith(prefix.rstrip("*")) for prefix in self.supported_commands)

class TransactionDriver(Protocol):
    def capture_checkpoint(self) -> str: ...
    def apply(self, commands: list[str]) -> None: ...
    def rollback(self, checkpoint: str) -> None: ...
    def verify(self) -> bool: ...

@dataclass
class TransactionResult:
    status: str
    checkpoint: str | None = None
    applied_commands: list[str] = field(default_factory=list)
    error: str | None = None
    rolled_back: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

def execute_transaction(driver: TransactionDriver, commands: list[str], capabilities: DeviceCapabilities,
                        *, approved: bool = False) -> TransactionResult:
    """Execute only explicitly approved, capability-permitted commands with rollback on failure."""
    if not approved:
        return TransactionResult(status="BLOCKED", error="Explicit approval is required.")
    if not commands:
        return TransactionResult(status="NOOP")
    for command in commands:
        if not capabilities.permits(command):
            return TransactionResult(status="BLOCKED", error=f"Command not permitted by device policy: {command}")
    if not capabilities.supports_checkpoint or not capabilities.supports_rollback:
        return TransactionResult(status="BLOCKED", error="Device policy requires checkpoint and rollback support.")
    checkpoint = None
    applied: list[str] = []
    try:
        checkpoint = driver.capture_checkpoint()
        driver.apply(commands)
        applied.extend(commands)
        if not driver.verify():
            raise RuntimeError("Post-change verification failed.")
        return TransactionResult(status="COMMITTED", checkpoint=checkpoint, applied_commands=applied)
    except Exception as exc:
        rolled_back = False
        rollback_error = None
        if checkpoint is not None:
            try:
                driver.rollback(checkpoint)
                rolled_back = True
            except Exception as rollback_exc:
                rollback_error = f"; rollback failed: {rollback_exc}"
        return TransactionResult(status="ROLLED_BACK" if rolled_back else "FAILED", checkpoint=checkpoint,
                                 applied_commands=applied, error=f"{exc}{rollback_error or ''}", rolled_back=rolled_back)

"""Conservative execution adapter for approved, explicitly safe remediation actions."""

from __future__ import annotations

from typing import Any

from netstate.exceptions import CollectionError
from netstate.models import RemediationAction


def apply_safe_actions(
    host: str,
    username: str,
    password: str,
    actions: list[RemediationAction],
    device_type: str = "cisco_ios",
    secret: str = "",
    port: int = 22,
    timeout: int = 15,
) -> list[dict[str, Any]]:
    """Apply actions explicitly marked auto_applicable, skipping higher-risk actions.

    This function never applies ACL or OSPF actions from the current planner. The caller must
    require an explicit confirmation flag before invoking it. A post-change audit is still needed.
    """
    approved = [action for action in actions if action.auto_applicable and action.commands]
    skipped = [action for action in actions if not action.auto_applicable]
    results: list[dict[str, Any]] = [
        {"path": action.path, "status": "SKIPPED_MANUAL_REVIEW", "reason": action.manual_review_reason}
        for action in skipped
    ]
    if not approved:
        return results

    try:
        from netmiko import ConnectHandler
    except ImportError as exc:
        raise CollectionError("SSH remediation requires Netmiko. Install with: pip install -e '.[ssh]'") from exc

    connection = None
    try:
        connection = ConnectHandler(
            device_type=device_type, host=host, username=username, password=password,
            secret=secret, port=port, conn_timeout=timeout, auth_timeout=timeout,
            banner_timeout=timeout,
        )
        if secret:
            connection.enable()
        for action in approved:
            try:
                output = connection.send_config_set(action.commands, read_timeout=max(timeout, 30))
                results.append({"path": action.path, "status": "COMMANDS_SENT", "commands": action.commands, "output": output})
            except Exception as exc:
                results.append({"path": action.path, "status": "FAILED", "error": str(exc)})
                # Stop after the first error. Subsequent changes may rely on the failed action.
                break
        try:
            connection.save_config()
        except Exception as exc:
            results.append({"path": "device.save_config", "status": "SAVE_FAILED", "error": str(exc)})
    except Exception as exc:
        raise CollectionError(f"Remediation session to {host} failed: {exc}") from exc
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass
    return results

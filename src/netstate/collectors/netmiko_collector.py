"""Optional live configuration collection for IOS devices that support SSH/Netmiko."""

from __future__ import annotations

from netstate.exceptions import CollectionError


def collect_from_ssh(
    host: str,
    username: str,
    password: str,
    device_type: str = "cisco_ios",
    secret: str = "",
    port: int = 22,
    timeout: int = 15,
) -> str:
    """Collect `show running-config`; requires the optional `ssh` dependency.

    This collector is for supported IOS devices / labs. It should not be assumed to work
    against Cisco Packet Tracer's simulated router CLI, which commonly lacks a general SSH
    automation interface.
    """
    try:
        from netmiko import ConnectHandler
    except ImportError as exc:
        raise CollectionError("SSH collection requires Netmiko. Install with: pip install -e '.[ssh]'") from exc

    connection = None
    try:
        connection = ConnectHandler(
            device_type=device_type,
            host=host,
            username=username,
            password=password,
            secret=secret,
            port=port,
            conn_timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
        )
        if secret:
            connection.enable()
        connection.send_command("terminal length 0", read_timeout=timeout)
        output = connection.send_command("show running-config", read_timeout=max(timeout, 30))
        if not output.strip():
            raise CollectionError(f"Device {host} returned an empty running configuration.")
        return output
    except CollectionError:
        raise
    except Exception as exc:  # Netmiko raises a family of connection/authentication exceptions.
        raise CollectionError(f"Could not collect configuration from {host}: {exc}") from exc
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass

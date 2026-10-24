"""Read a saved Cisco IOS running-config export."""

from pathlib import Path

from netstate.exceptions import CollectionError


def collect_from_file(path: str | Path) -> str:
    target = Path(path)
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CollectionError(f"Cannot read configuration file '{target}': {exc}") from exc
    if not content.strip():
        raise CollectionError(f"Configuration file '{target}' is empty.")
    return content

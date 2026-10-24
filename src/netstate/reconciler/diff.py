"""Desired-versus-actual state comparison."""

from __future__ import annotations

from typing import Any

from netstate.models import Drift, Severity


def _severity(path: str) -> Severity:
    lower = path.lower()
    if ".acls." in lower or lower.startswith("acls.") or ".access_groups." in lower:
        return "CRITICAL" if ".acls." in lower or lower.startswith("acls.") else "HIGH"
    if ".ipv4_" in lower:
        return "HIGH"
    if ".admin_state" in lower or ".ospf." in lower or lower.startswith("ospf."):
        return "HIGH"
    if lower == "hostname":
        return "LOW"
    return "MEDIUM"


def _equal(path: str, left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        if path.endswith(".admin_state"):
            return left.strip().lower() == right.strip().lower()
        if path.endswith(".description"):
            return left.strip() == right.strip()
        return left == right
    return left == right


def compare_states(desired: dict[str, Any], actual: dict[str, Any]) -> list[Drift]:
    """Return drift findings for desired fields. Unspecified fields are not managed.

    Lists are compared as ordered values. This is intentional for ACL entries because ACL
    order can change packet-filtering semantics. Set ``strict: true`` to additionally flag
    actual interfaces, ACLs, and OSPF processes that are absent from the desired document.
    """
    findings: list[Drift] = []

    def walk(wanted: Any, observed: Any, path: str) -> None:
        if isinstance(wanted, dict):
            if not isinstance(observed, dict):
                findings.append(Drift(path, wanted, observed, _severity(path), f"Expected a mapping at {path}, got {type(observed).__name__}."))
                return
            for key, expected_value in wanted.items():
                child = f"{path}.{key}" if path else str(key)
                if key not in observed:
                    # Explicit null means "this property should be absent" for nullable
                    # modeled fields such as an IP address or interface description.
                    if expected_value is None:
                        continue
                    findings.append(Drift(child, expected_value, None, _severity(child), f"Required configuration is missing at {child}."))
                else:
                    walk(expected_value, observed[key], child)
            return
        if not _equal(path, wanted, observed):
            if isinstance(wanted, list) and isinstance(observed, list):
                message = f"Ordered list differs at {path}; ACL entry order may be significant."
            else:
                message = f"Actual value differs from desired state at {path}."
            findings.append(Drift(path, wanted, observed, _severity(path), message))

    for key, wanted in desired.items():
        if key == "strict":
            continue
        if key not in actual:
            if key in {"interfaces", "acls", "ospf"} and isinstance(wanted, dict):
                walk(wanted, {}, key)
            else:
                findings.append(Drift(key, wanted, None, _severity(key), f"Required configuration section '{key}' is missing."))
        else:
            walk(wanted, actual[key], key)

    if desired.get("strict", False):
        for section in ("interfaces", "acls", "ospf"):
            wanted_names = set(desired.get(section, {}))
            actual_names = set(actual.get(section, {}))
            for unexpected in sorted(actual_names - wanted_names, key=str):
                path = f"{section}.{unexpected}"
                findings.append(Drift(path, None, actual[section][unexpected], _severity(path), f"Unexpected {section[:-1] if section.endswith('s') else section} exists and strict mode is enabled."))
    return findings

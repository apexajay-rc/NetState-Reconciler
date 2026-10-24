"""Multi-device inventory loading and repeatable read-only SSH audits."""
from __future__ import annotations
import yaml
from pathlib import Path
from netstate.collectors.netmiko_collector import collect_from_ssh
from netstate.configuration import load_desired
from netstate.parsers.ios import CiscoIOSParser
from netstate.reconciler.diff import compare_states
from netstate.models import AuditReport

def load_inventory(path: str | Path) -> list[dict]:
    raw=yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or not isinstance(raw.get("devices"), list): raise ValueError("Inventory must contain a devices list")
    names=set()
    for d in raw["devices"]:
        if not isinstance(d, dict) or not all(d.get(k) for k in ("name","host","username","desired_file")):
            raise ValueError("Each device requires name, host, username, and desired_file")
        if d["name"] in names: raise ValueError(f"Duplicate inventory device: {d['name']}")
        names.add(d["name"])
    return raw["devices"]

def audit_inventory(path: str | Path, *, password_env: str="NETSTATE_DEVICE_PASSWORD") -> list[dict]:
    """Collect and audit each device. Credentials are supplied via environment, never inventory YAML."""
    import os
    password=os.environ.get(password_env)
    if not password: raise ValueError(f"Set {password_env} in the environment; do not store passwords in inventory")
    results=[]
    for d in load_inventory(path):
        try:
            config=collect_from_ssh(d["host"], d["username"], password, d.get("device_type","cisco_ios"),
                                    os.environ.get("NETSTATE_ENABLE_SECRET", ""), int(d.get("port",22)))
            parser=CiscoIOSParser()
            actual=parser.parse(config)
            desired=load_desired(d["desired_file"])
            drifts=compare_states(desired, actual)
            report=AuditReport(device=str(actual.get("hostname") or d["name"]), compliant=not drifts and not parser.warnings,
                               desired_file=d["desired_file"], source=f"ssh://{d['host']}", drifts=drifts,
                               parser_warnings=parser.warnings)
            results.append({"device":d["name"],"status":"COMPLIANT" if report.compliant else "NON-COMPLIANT",
                            "report":report.to_dict()})
        except Exception as exc: results.append({"device":d["name"],"status":"ERROR","error":str(exc)})
    return results

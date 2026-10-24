"""Repeatable scheduled audit runner; use systemd/cron or invoke this module periodically."""
from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
from pathlib import Path
from netstate.inventory import audit_inventory

def run_once(inventory: str, output_dir: str) -> Path:
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    results=audit_inventory(inventory)
    target=out/f'audit-{stamp}.json'
    target.write_text(json.dumps({"timestamp":stamp,"results":results},indent=2)+"\n")
    return target

def main():
    p=argparse.ArgumentParser(description="Repeatable NetState inventory audit runner")
    p.add_argument("--inventory",required=True); p.add_argument("--output-dir",default="reports/scheduled")
    p.add_argument("--interval-seconds",type=int,default=0,help="0 runs once; positive repeats at this interval")
    a=p.parse_args()
    if a.interval_seconds < 0: p.error("interval must be >= 0")
    while True:
        print(run_once(a.inventory,a.output_dir))
        if not a.interval_seconds: break
        time.sleep(a.interval_seconds)
if __name__ == '__main__': main()

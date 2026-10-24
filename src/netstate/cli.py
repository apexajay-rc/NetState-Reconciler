"""Command-line interface for NetState Reconciler."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from netstate import __version__
from netstate.collectors.file import collect_from_file
from netstate.collectors.netmiko_collector import collect_from_ssh
from netstate.configuration import load_desired
from netstate.exceptions import NetStateError
from netstate.models import AuditReport
from netstate.parsers.ios import CiscoIOSParser
from netstate.reconciler.diff import compare_states
from netstate.remediation.executor import apply_safe_actions
from netstate.remediation.planner import build_plan


def _add_source_arguments(parser: argparse.ArgumentParser, require_host: bool = False) -> None:
    source = parser.add_mutually_exclusive_group(required=not require_host)
    source.add_argument("--source", help="Path to an exported 'show running-config' text file.")
    source.add_argument("--host", help="Device hostname or management IP for SSH collection.")
    parser.add_argument("--username", default=os.getenv("NETSTATE_USERNAME"), help="SSH username (or NETSTATE_USERNAME).")
    parser.add_argument("--device-type", default="cisco_ios", help="Netmiko device_type (default: cisco_ios).")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22).")
    parser.add_argument("--timeout", type=int, default=15, help="Connection timeout in seconds.")


def _credentials(args: argparse.Namespace) -> tuple[str, str, str]:
    username = args.username or input(f"SSH username for {args.host}: ").strip()
    if not username:
        raise NetStateError("SSH username cannot be empty.")
    password = os.getenv("NETSTATE_PASSWORD")
    if password is None:
        password = getpass.getpass(f"SSH password for {username}@{args.host}: ")
    secret = os.getenv("NETSTATE_ENABLE_SECRET", "")
    return username, password, secret


def _collect(args: argparse.Namespace) -> tuple[str, str]:
    if args.source:
        return collect_from_file(args.source), str(Path(args.source))
    username, password, secret = _credentials(args)
    text = collect_from_ssh(
        host=args.host, username=username, password=password, secret=secret,
        device_type=args.device_type, port=args.port, timeout=args.timeout,
    )
    return text, f"ssh://{args.host}:{args.port}"


def _audit(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], AuditReport, list[Any]]:
    desired = load_desired(args.desired)
    raw_config, source = _collect(args)
    ios_parser = CiscoIOSParser()
    actual = ios_parser.parse(raw_config)
    drifts = compare_states(desired, actual)
    report = AuditReport(
        device=str(actual.get("hostname") or (args.host if getattr(args, "host", None) else "unknown")),
        compliant=not drifts and not ios_parser.warnings,
        desired_file=str(args.desired), source=source, drifts=drifts,
        parser_warnings=ios_parser.warnings,
    )
    return desired, actual, report, drifts


def _print_audit(report: AuditReport) -> None:
    print("NetState Reconciler — Configuration Audit")
    print("=" * 43)
    print(f"Device:  {report.device}")
    print(f"Source:  {report.source}")
    print(f"Desired: {report.desired_file}")
    if report.compliant:
        status = "COMPLIANT"
    elif report.parser_warnings and not report.drifts:
        status = "INCOMPLETE (PARSER WARNINGS)"
    else:
        status = "NON-COMPLIANT" if report.drifts else "INCOMPLETE (PARSER WARNINGS)"
    print(f"Status:  {status}")
    print(f"Drifts:  {len(report.drifts)}")
    if report.drifts:
        print("\nFindings:")
        for index, drift in enumerate(report.drifts, start=1):
            print(f"  {index}. [{drift.severity}] {drift.path}")
            print(f"     desired: {json.dumps(drift.desired, ensure_ascii=False)}")
            print(f"     actual:  {json.dumps(drift.actual, ensure_ascii=False)}")
            print(f"     detail:  {drift.message}")
    if report.parser_warnings:
        print("\nParser warnings (review before relying on a clean audit):")
        for warning in report.parser_warnings:
            print(f"  - {warning}")


def _save_json(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nJSON report written to: {target}")


def _cmd_validate(args: argparse.Namespace) -> int:
    desired = load_desired(args.desired)
    print(f"Valid desired-state file: {args.desired}")
    print(f"Managed sections: {', '.join(k for k in ('hostname', 'interfaces', 'acls', 'ospf') if k in desired)}")
    print(f"Strict resource checking: {'enabled' if desired.get('strict', False) else 'disabled'}")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    _, _, report, _ = _audit(args)
    _print_audit(report)
    _save_json(args.json_output, report.to_dict())
    return 0 if report.compliant else 1


def _cmd_plan(args: argparse.Namespace) -> int:
    desired, actual, report, drifts = _audit(args)
    actions = build_plan(desired, actual, drifts)
    _print_audit(report)
    print("\nRemediation plan (not executed):")
    if not actions:
        print("  No actions required.")
    for index, action in enumerate(actions, start=1):
        status = "AUTO-APPLICABLE AFTER EXPLICIT CONFIRMATION" if action.auto_applicable else "MANUAL REVIEW REQUIRED"
        print(f"  {index}. [{action.severity}] {action.path}: {action.summary}")
        print(f"     status: {status}")
        for command in action.commands:
            print(f"       {command}")
        if action.manual_review_reason:
            print(f"     reason: {action.manual_review_reason}")
    payload = {"audit": report.to_dict(), "actions": [action.to_dict() for action in actions]}
    _save_json(args.json_output, payload)
    return 0 if report.compliant else 1


def _cmd_apply(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise NetStateError("Refusing to apply changes without --confirm. Run 'netstate plan' first.")
    desired = load_desired(args.desired)
    username, password, secret = _credentials(args)
    raw_config = collect_from_ssh(
        host=args.host, username=username, password=password, secret=secret,
        device_type=args.device_type, port=args.port, timeout=args.timeout,
    )
    parser = CiscoIOSParser()
    actual = parser.parse(raw_config)
    drifts = compare_states(desired, actual)
    actions = build_plan(desired, actual, drifts)
    before = AuditReport(
        device=str(actual.get("hostname") or args.host), compliant=not drifts and not parser.warnings,
        desired_file=args.desired, source=f"ssh://{args.host}:{args.port}",
        drifts=drifts, parser_warnings=parser.warnings,
    )
    _print_audit(before)
    if parser.warnings:
        print("\nRefusing remediation because parser warnings mean the audit is incomplete.", file=sys.stderr)
        return 2
    if not actions:
        print("\nNo remediation required.")
        return 0 if before.compliant else 1
    print("\nThis apply mode executes only actions marked auto-applicable by the planner.")
    print("ACL, OSPF, interface-address, interface-admin-state, and ACL-binding changes may require manual review.")
    results = apply_safe_actions(
        host=args.host, username=username, password=password, secret=secret,
        device_type=args.device_type, port=args.port, timeout=args.timeout, actions=actions,
    )
    print("\nExecution results:")
    for result in results:
        print(f"  {result['status']}: {result['path']}")
        if result.get("reason"):
            print(f"    reason: {result['reason']}")
        if result.get("error"):
            print(f"    error: {result['error']}")
    print("\nRe-collecting configuration for post-change verification...")
    after_text = collect_from_ssh(
        host=args.host, username=username, password=password, secret=secret,
        device_type=args.device_type, port=args.port, timeout=args.timeout,
    )
    verify_parser = CiscoIOSParser()
    after_actual = verify_parser.parse(after_text)
    after_drifts = compare_states(desired, after_actual)
    after = AuditReport(
        device=str(after_actual.get("hostname") or args.host), compliant=not after_drifts and not verify_parser.warnings,
        desired_file=args.desired, source=f"ssh://{args.host}:{args.port}",
        drifts=after_drifts, parser_warnings=verify_parser.warnings,
    )
    _print_audit(after)
    _save_json(args.json_output, {"before": before.to_dict(), "execution": results, "after": after.to_dict()})
    return 0 if after.compliant else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netstate", description="Audit, plan, and cautiously remediate Cisco IOS configuration drift."
    )
    parser.add_argument("--version", action="version", version=f"NetState Reconciler {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate desired-state YAML.")
    validate.add_argument("--desired", required=True, help="Desired-state YAML file.")
    validate.set_defaults(handler=_cmd_validate)

    for command, help_text, handler in (
        ("audit", "Compare actual configuration against desired state.", _cmd_audit),
        ("plan", "Show drift and proposed remediation without executing it.", _cmd_plan),
    ):
        child = subparsers.add_parser(command, help=help_text)
        child.add_argument("--desired", required=True, help="Desired-state YAML file.")
        _add_source_arguments(child)
        child.add_argument("--json-output", help="Optional path to write a JSON report.")
        child.set_defaults(handler=handler)

    apply_parser = subparsers.add_parser("apply", help="Apply only planner-approved actions over SSH, then verify.")
    apply_parser.add_argument("--desired", required=True, help="Desired-state YAML file.")
    apply_parser.add_argument("--host", required=True, help="Device hostname or management IP for SSH remediation.")
    apply_parser.add_argument("--username", default=os.getenv("NETSTATE_USERNAME"), help="SSH username (or NETSTATE_USERNAME).")
    apply_parser.add_argument("--device-type", default="cisco_ios", help="Netmiko device_type (default: cisco_ios).")
    apply_parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22).")
    apply_parser.add_argument("--timeout", type=int, default=15, help="Connection timeout in seconds.")
    apply_parser.add_argument("--confirm", action="store_true", help="Confirm execution of auto-applicable changes.")
    apply_parser.add_argument("--json-output", help="Optional path to write execution and verification results.")
    apply_parser.set_defaults(handler=_cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (NetStateError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

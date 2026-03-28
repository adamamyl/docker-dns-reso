#!/usr/bin/env python3
"""
coordinator.py — macOS DNS diagnostic coordinator.

Runs all diagnostic modules as discrete pass/fail checks and produces a report
oriented around the macOS 26 mDNSResponder / Quad9 profile interception bug.

Execution order:
  1. resolver   — tests the /etc/resolver/ → dnsmasq → getaddrinfo chain
  2. mdns       — checks for mDNS interception fingerprint and conflicting profiles
  3. quad9      — regression test: is the Quad9 profile installed, does .internal resolve?
  4. docker_dns — tests resolution from inside a Docker container (heaviest check)

Usage:
    python coordinator.py [--dry-run] [--verbose] [--debug] [--skip MODULE,...]

Exit code: 0 if all checks pass or warn, 1 if any check fails or errors.
"""

import argparse
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from modules import docker_dns, mdns, openvpn, quad9, resolver
from modules import logger as logmod
from modules.types import CheckResult, Status

_SNAPSHOT_DIR = Path("snapshots")

_STATUS_STYLE: dict[Status, str] = {
    "pass": "[bold green]PASS[/bold green]",
    "fail": "[bold red]FAIL[/bold red]",
    "warn": "[bold yellow]WARN[/bold yellow]",
    "skip": "[dim]SKIP[/dim]",
    "error": "[bold red]ERROR[/bold red]",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="macOS DNS diagnostic coordinator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Modules: resolver, mdns, quad9, openvpn, docker_dns",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not execute external commands")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--debug", action="store_true", help="Debug logging (very chatty)")
    parser.add_argument(
        "--skip", default="", metavar="MODULE,...", help="Comma-separated module names to skip (e.g. --skip docker_dns)"
    )
    return parser.parse_args()


def _overall_status(results: list[CheckResult]) -> Status:
    statuses = {r["status"] for r in results}
    if statuses & {"fail", "error"}:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def save_diagnostic(results: list[CheckResult], run_id: str, overall: Status) -> Path:
    """Write all check results to snapshots/run-{run_id}/diagnostic.json."""
    out_dir = _SNAPSHOT_DIR / f"run-{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "diagnostic.json"
    payload = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "overall": overall,
        "results": list(results),
    }
    out_file.write_text(json.dumps(payload, indent=2))
    return out_file


def print_report(results: list[CheckResult], run_id: str, snapshot_path: Path, overall: Status) -> None:
    """Render a Rich summary table, then detail blocks for any non-passing checks."""
    console = Console()

    table = Table(title=f"macOS DNS Diagnostic — {run_id}", show_lines=True)
    table.add_column("Module", style="bold cyan", min_width=12)
    table.add_column("Status", justify="center", min_width=8)
    table.add_column("Summary")

    for r in results:
        table.add_row(r["module"], _STATUS_STYLE[r["status"]], r["summary"])

    console.print(table)

    for r in results:
        if r["status"] not in ("fail", "error", "warn"):
            continue
        if not r["details"] and not r["errors"]:
            continue
        console.print(f"\n[bold cyan]{r['module']} details:[/bold cyan]")
        for key, value in r["details"].items():
            console.print(f"  [dim]{key}:[/dim] {value}")
        for err in r["errors"]:
            console.print(f"  [red]error:[/red] {err}")

    console.print(f"\nOverall: {_STATUS_STYLE[overall]}")
    console.print(f"[dim]Saved: {snapshot_path}[/dim]")


def main() -> None:
    args = parse_args()
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = logmod.configure_logger(quiet=False, verbose=args.verbose, debug=args.debug)
    skip: set[str] = set(filter(None, args.skip.split(",")))

    checks: list[tuple[str, Callable[[], CheckResult]]] = [
        ("resolver", lambda: resolver.run_checks(log=log, dry_run=args.dry_run)),
        ("mdns", lambda: mdns.run_checks(log=log, dry_run=args.dry_run)),
        ("quad9", lambda: quad9.run_checks(log=log, dry_run=args.dry_run)),
        ("openvpn", lambda: openvpn.run_checks(log=log, dry_run=args.dry_run)),
        ("docker_dns", lambda: docker_dns.run_checks(log=log, dry_run=args.dry_run)),
    ]

    results: list[CheckResult] = []
    for name, fn in checks:
        if name in skip:
            results.append(
                CheckResult(
                    module=name,
                    status="skip",
                    summary="skipped via --skip",
                    details={},
                    errors=[],
                )
            )
            continue
        log.module_start(name)
        try:
            results.append(fn())
        except Exception as exc:
            log.error(f"{name} raised an unexpected exception: {exc}")
            results.append(
                CheckResult(
                    module=name,
                    status="error",
                    summary=str(exc),
                    details={},
                    errors=[repr(exc)],
                )
            )

    overall = _overall_status(results)
    snapshot_path = save_diagnostic(results, run_id, overall)
    print_report(results, run_id, snapshot_path, overall)

    failed = [r for r in results if r["status"] in ("fail", "error")]
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

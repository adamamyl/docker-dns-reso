#!/usr/bin/env python3
"""
Main orchestrator for net-tester

- Handles scenarios: pom, pom+dnsmasq, pom+docker, pom+tailscale, etc.
- Captures network/system state using capture module
- Manages Docker, Tailscale, DNSMasq modules
- Respects logging flags (--dry-run, --verbose, --quiet, --debug)
- Saves snapshots in JSON (NDJSON for processes)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Modules
from modules import capture, dnsmasq, docker, install_utils
from modules import logger as logmod
from modules import tailscale


# -----------------------------
# Setup constants
# -----------------------------
def generate_run_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


RUN_ID = generate_run_id()
BASE_SNAPSHOT_DIR = Path("snapshots") / f"run-{RUN_ID}"
BASE_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------
# Argument parsing
# -----------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Net-tester orchestrator")
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not execute external commands"
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--quiet", action="store_true", help="Minimal logging")
    parser.add_argument("--debug", action="store_true", help="Debug logging")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force actions in modules (e.g., tailscale up)",
    )
    parser.add_argument(
        "--module",
        type=str,
        default="all",
        help="Run only selected module: ps,dnsmasq,docker,tailscale,all",
    )
    parser.add_argument("--run-id", type=str, help="Override auto-generated run ID")
    return parser.parse_args()


# -----------------------------
# Snapshot helper
# -----------------------------
def save_snapshot(name, state, stage="after"):
    """
    Saves snapshot JSON and NDJSON (processes)
    stage: 'before' or 'after'
    """
    path = BASE_SNAPSHOT_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    file = path / f"{RUN_ID}_{name}_{stage}.json"

    # Processes NDJSON as separate file
    processes_ndjson = state.pop("processes", "")
    file.write_text(json.dumps(state, indent=2))
    if processes_ndjson:
        (path / f"{RUN_ID}_{name}_{stage}_processes.ndjson").write_text(
            processes_ndjson
        )
    return file


# -----------------------------
# Orchestrator
# -----------------------------
def main():
    args = parse_args()

    # Override RUN_ID if provided
    global RUN_ID, BASE_SNAPSHOT_DIR
    if args.run_id:
        RUN_ID = args.run_id
        BASE_SNAPSHOT_DIR = Path("snapshots") / f"run-{RUN_ID}"
        BASE_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # Configure logger
    log = logmod.configure_logger(
        quiet=args.quiet, verbose=args.verbose, debug=args.debug
    )
    log_module_start = log.module_start

    scenarios = [
        {"name": "pom"},
        {"name": "pom+dnsmasq"},
        {"name": "pom+docker"},
        {"name": "pom+docker+dnsmasq"},
        {"name": "pom+docker+tailscale"},
    ]

    for sc in scenarios:
        if args.module != "all" and args.module not in sc["name"]:
            log.info(f"Skipping scenario '{sc['name']}' (not in --module)")
            continue

        log.info(f"=== Running scenario: {sc['name']} ===")

        # Capture network/system state
        state = capture.capture_network_state()
        sc["state"] = state

        # Docker management
        if "docker" in sc["name"]:
            log_module_start("Docker")
            if docker.wait_for_docker(timeout=30, log=log):
                log.success("Docker daemon running")
            else:
                log.warn("Docker daemon not running after timeout")
            sc["docker"] = True

        # DNSMasq management
        if "dnsmasq" in sc["name"]:
            log_module_start("DNSMasq")
            dnsmasq.ensure_config(log=log, dry_run=args.dry_run)
            dnsmasq.restart_service(log=log, dry_run=args.dry_run)
            sc["dnsmasq"] = True

        # Tailscale management
        if "tailscale" in sc["name"]:
            log_module_start("Tailscale")
            tailscale.run_tailscale_module(
                logger=log, force=args.force, dry_run=args.dry_run
            )
            sc["tailscale"] = True

        # Save snapshot
        save_snapshot(sc["name"], state)
        log.info(f"=== Scenario '{sc['name']}' complete ===")

    # Summary table
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title=f"Network Tester Summary ({RUN_ID})")
    table.add_column("Scenario")
    table.add_column("Processes", justify="center")
    table.add_column("Docker", justify="center")
    table.add_column("DNSMasq", justify="center")
    table.add_column("Tailscale", justify="center")
    for sc in scenarios:
        if "state" not in sc:
            continue
        table.add_row(
            sc["name"],
            str(len(sc["state"].get("processes", "").splitlines())),
            "✅" if sc.get("docker") else "-",
            "✅" if sc.get("dnsmasq") else "-",
            "✅" if sc.get("tailscale") else "-",
        )
    console.print(table)

    # Optional: send detailed logs to ChatGPT (manual)
    if not args.quiet:
        resp = input("Send detailed logs to ChatGPT in chunks? [y/N] ").lower()
        if resp == "y":
            from modules.chatgpt import send_to_chatgpt  # Optional module

            for sc in scenarios:
                if "state" in sc:
                    send_to_chatgpt(
                        json.dumps(sc["state"], indent=2), scenario=sc["name"]
                    )


# -----------------------------
# Entry point
# -----------------------------
if __name__ == "__main__":
    main()

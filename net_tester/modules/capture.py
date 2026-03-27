# net-tester/modules/capture.py
"""
Capture network and system state on macOS for net-tester.

- Processes: NDJSON (diagnostic, not for diffing)
- Network: interfaces, addresses, routes
- DNS: summarized per-interface, compact JSON for diffing
- Sample DNS query using 'doggo' if available
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

import modules.logger as logmod
from modules.install_utils import command_path, get_brew_prefix, run_cmd


# [CURRENT]
def capture_processes(
    dry_run: bool = False, check: bool = True, capture_output: bool = True
) -> str:
    """
    Capture the currently running processes as NDJSON.
    Each line is a JSON object describing a single process.
    """
    try:
        output = run_cmd(
            ["ps", "-axo", "pid,ppid,uid,gid,comm"],
            dry_run=dry_run,
            check=check,
            capture_output=capture_output,
        ).stdout.strip().splitlines()
    except Exception:
        return ""

    ndjson_lines = []
    for line in output[1:]:  # skip header
        parts = line.strip().split(None, 4)
        if len(parts) != 5:
            continue

        pid, ppid, uid, gid, comm = parts
        if not pid.isdigit() or not uid.isdigit():
            continue

        proc_dict = {
            "pid": int(pid),
            "ppid": int(ppid),
            "uid": int(uid),
            "gid": int(gid),
            "comm": comm,
            "is_root": int(uid) == 0,
        }
        ndjson_lines.append(json.dumps(proc_dict))

    return "\n".join(ndjson_lines)


# [CURRENT]
def capture_dns_summary(
    dry_run: bool = False, check: bool = True, capture_output: bool = True
) -> Dict[str, Dict]:
    """
    Capture a compact DNS summary for diffing snapshots.
    Summarizes per resolver/interface info, reducing the full scutil --dns output (~100 lines)
    to a digestible structure.
    """
    dns_summary = {}
    try:
        scutil_output = run_cmd(
            ["scutil", "--dns"], dry_run=dry_run, check=check, capture_output=capture_output
        ).stdout.splitlines()
    except Exception:
        return dns_summary

    current_iface = None
    for line in scutil_output:
        line = line.strip()
        if line.startswith("resolver #"):
            current_iface = line
            dns_summary[current_iface] = {}
        elif current_iface:
            if line.startswith("nameserver["):
                dns_summary[current_iface].setdefault("nameservers", []).append(
                    line.split(":", 1)[1].strip()
                )
            elif line.startswith("search domain["):
                dns_summary[current_iface].setdefault("search_domains", []).append(
                    line.split(":", 1)[1].strip()
                )
            elif line.startswith("interface:"):
                dns_summary[current_iface]["interface"] = line.split(":", 1)[1].strip()

    return dns_summary


# [CURRENT]
def doggo_query(
    domain: str = "example.com",
    dry_run: bool = False,
    check: bool = True,
    capture_output: bool = True,
) -> Dict[str, Optional[str]]:
    """
    Sample DNS query using 'doggo' if available.
    """
    try:
        result = run_cmd(
            ["doggo", domain],
            dry_run=dry_run,
            check=check,
            capture_output=capture_output,
        )
        return {"doggo_output": result.stdout.decode()}
    except FileNotFoundError:
        logmod.get_logger().warning("Doggo not installed, skipping DNS query")
        return {"doggo_output": None}


# [CURRENT]
def capture_network_state(dry_run: bool = False) -> Dict[str, Any]:
    """
    Capture full network state:

    - interfaces
    - addresses
    - routes
    - processes (NDJSON)
    - DNS summary + sample doggo resolution
    """
    state: Dict[str, Any] = {}

    # Determine binaries
    ip_bin = command_path("ip") or f"{get_brew_prefix()}/bin/ip"
    doggo_bin = command_path("doggo") or f"{get_brew_prefix()}/bin/doggo"

    # Interfaces / addresses / routes
    for attr, cmd in [
        ("interfaces", [ip_bin, "-j", "link"]),
        ("addresses", [ip_bin, "-j", "addr"]),
        ("routes", [ip_bin, "-j", "route"]),
    ]:
        try:
            state[attr] = json.loads(run_cmd(cmd, dry_run=dry_run).stdout)
        except Exception:
            state[attr] = []

    # DNS
    resolv_conf = ""
    dns_summary = {}
    sample_dns = ""
    try:
        resolv_conf = Path("/etc/resolv.conf").read_text()
        dns_summary = capture_dns_summary(dry_run=dry_run)

        if doggo_bin:
            sample_dns = doggo_query("tailscale.com", dry_run=dry_run)["doggo_output"]
    except Exception:
        pass

    state["dns"] = {
        "summary": dns_summary,
        "resolv_conf": resolv_conf,
        "doggo_sample": sample_dns,
    }

    # Processes (NDJSON)
    state["processes"] = capture_processes(dry_run=dry_run)

    return state

# modules/dnsmasq.py
"""
DNSMasq module for net-tester

Provides functions to check if dnsmasq is running, capture its
state for snapshots, and optionally inspect config files / leases.
"""

import subprocess
from pathlib import Path
from .logger import log

def run_cmd(cmd, check=True, capture=True):
    """Helper to run a shell command and return result."""
    result = subprocess.run(cmd, capture_output=capture, text=True, check=check)
    return result.stdout.strip()

def is_running() -> bool:
    """
    Check if dnsmasq process is currently running.
    Returns True if at least one process is found, else False.
    """
    try:
        output = run_cmd(["pgrep", "-x", "dnsmasq"], check=False)
        return bool(output)
    except Exception as e:
        log.warning(f"Error checking dnsmasq status: {e}")
        return False

def capture_state() -> dict:
    """
    Capture current dnsmasq state for logging / snapshot purposes.
    Includes:
      - running status
      - active PIDs
      - configuration files (if accessible)
      - leases (if accessible)
    """
    state = {"running": False, "pids": [], "configs": [], "leases": None}

    # Detect running processes
    try:
        pids_output = run_cmd(["pgrep", "-x", "dnsmasq"], check=False)
        pids = [int(pid) for pid in pids_output.splitlines() if pid.isdigit()]
        state["pids"] = pids
        state["running"] = bool(pids)
    except Exception as e:
        log.warning(f"Failed to capture dnsmasq PIDs: {e}")

    # Config files (typical locations, adjust if needed)
    possible_configs = ["/etc/dnsmasq.conf", "/usr/local/etc/dnsmasq.conf"]
    for cfg in possible_configs:
        cfg_path = Path(cfg)
        if cfg_path.exists():
            state["configs"].append(str(cfg_path))

    # Lease file (if exists)
    lease_file = Path("/var/db/dnsmasq.leases")
    if lease_file.exists():
        try:
            state["leases"] = lease_file.read_text().splitlines()
        except Exception as e:
            log.warning(f"Failed to read dnsmasq leases: {e}")

    return state

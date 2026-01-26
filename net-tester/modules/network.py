import json
from pathlib import Path
from typing import Dict

from net_tester.utils import run_cmd, command_path


def capture_network_state(log, args) -> Dict[str, object]:
    """
    Capture network interfaces, addresses, routes, and DNS state.

    Failures are tolerated — missing tools or permissions
    should not abort the run.
    """
    state = {}

    ip_bin = command_path("ip")
    doggo_bin = command_path("doggo")

    if ip_bin:
        try:
            state["interfaces"] = json.loads(run_cmd([ip_bin, "-j", "link"]).stdout)
            state["addresses"] = json.loads(run_cmd([ip_bin, "-j", "addr"]).stdout)
            state["routes"] = json.loads(run_cmd([ip_bin, "-j", "route"]).stdout)
        except Exception as e:
            log.debug(f"Failed to capture ip state: {e}")
            state["interfaces"] = []
            state["addresses"] = []
            state["routes"] = []
    else:
        state["interfaces"] = []
        state["addresses"] = []
        state["routes"] = []

    try:
        scutil_dns = run_cmd(["scutil", "--dns"], check=False).stdout
        resolv_conf = Path("/etc/resolv.conf").read_text()

        dns_sample = None
        if doggo_bin:
            dns_sample = run_cmd(
                [doggo_bin, "resolve", "tailscale.com"],
                check=False,
            ).stdout.strip()

        state["dns"] = {
            "scutil": scutil_dns,
            "resolv_conf": resolv_conf,
            "sample_lookup": dns_sample,
        }
    except Exception as e:
        log.debug(f"DNS capture failed: {e}")
        state["dns"] = {}

    return state

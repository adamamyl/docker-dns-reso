import json
import subprocess
from typing import Dict, List

from net_tester.utils import run_cmd, command_path, sleep


def run_tailscale(log, args) -> Dict[str, object]:
    """
    Validate and probe Tailscale state.

    Logging is summary-level unless debug is enabled.
    Raw status JSON is never printed unless debug.
    """
    result = {
        "running": False,
        "ip": None,
        "iface": None,
        "peers": [],
        "errors": [],
    }

    log.module_start("tailscale", args)

    ts_gui = run_cmd(["pgrep", "-f", "Tailscale"], check=False).stdout.strip().split()
    tsd = run_cmd(["pgrep", "-f", "tailscaled"], check=False).stdout.strip().split()

    if ts_gui:
        log.info(f"Tailscale GUI detected ({len(ts_gui)} process)")
    if tsd:
        log.info("tailscaled daemon running")

    tsd_bin = command_path("tailscaled")

    if not tsd and tsd_bin and not args.dry_run:
        log.info("Starting tailscaled")
        subprocess.Popen(
            ["sudo", tsd_bin],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        sleep(5)
        tsd = run_cmd(["pgrep", "-f", "tailscaled"], check=False).stdout.strip().split()

    if not ts_gui and not tsd:
        result["errors"].append("Tailscale not running")
        log.warning("No Tailscale processes detected")
        return result

    try:
        raw = run_cmd(["tailscale", "status", "--json"]).stdout
        status = json.loads(raw)

        if args.debug:
            log.debug("tailscale status JSON captured")

    except Exception as e:
        result["errors"].append(str(e))
        log.error("Failed to query tailscale status")
        return result

    self_ips = status.get("Self", {}).get("TailscaleIPs", [])
    peers_raw = status.get("Peer", {})

    peers: List[dict]
    if isinstance(peers_raw, dict):
        peers = list(peers_raw.values())
    else:
        peers = peers_raw

    ts_ip = next((ip for ip in self_ips if ip.startswith("100.")), None)

    result.update(
        {
            "running": True,
            "ip": ts_ip,
            "iface": "tailscale",
            "peers": [
                {
                    "host": p.get("HostName"),
                    "online": p.get("Online"),
                    "ips": p.get("TailscaleIPs", []),
                }
                for p in peers
            ],
        }
    )

    log.success("Tailscale module complete")
    return result

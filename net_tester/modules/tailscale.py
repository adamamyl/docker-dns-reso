"""
tailscale.py
Module to check and interact with Tailscale on macOS.
Uses logger and install_utils.command_path for robust binary resolution.
"""

import json
import time
import subprocess

from modules.install_utils import command_path
import modules.logger


def run_tailscale_module(logger=None, force=True, dry_run=False):
    """
    Checks Tailscale GUI/daemon, ensures tailscaled is running, and pings reachable tailnet devices.
    Uses logger for output and respects dry_run and force flags.
    """
    log = logger or modules.logger.log
    log.module_start("Tailscale")

    doggo_bin = command_path("doggo")
    tailscale_bin = command_path("tailscale")
    tailscaled_bin = command_path("tailscaled")

    if not tailscale_bin or not tailscaled_bin:
        log.error("Required Tailscale binaries not found. Exiting module.")
        return

    ts_gui_pids = subprocess.run(["pgrep", "-f", "Tailscale"], capture_output=True, text=True).stdout.strip().split()
    if ts_gui_pids:
        log.info(f"Tailscale GUI detected (PIDs {ts_gui_pids})")
    else:
        log.info("Tailscale GUI not running")

    tsd_pids = subprocess.run(["pgrep", "-f", "tailscaled"], capture_output=True, text=True).stdout.strip().split()

    # Start tailscaled non-blocking if not running
    if not tsd_pids:
        log.info(f"Starting tailscaled daemon: {tailscaled_bin}")
        if not dry_run:
            subprocess.Popen(
                ["sudo", tailscaled_bin],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(5)
            tsd_pids = (
                subprocess.run(["pgrep", "-f", "tailscaled"], capture_output=True, text=True).stdout.strip().split()
            )

    if not ts_gui_pids and not tsd_pids:
        log.warn("No Tailscale processes detected.")
        if force:
            log.info("Running: tailscale up --force")
            if not dry_run:
                subprocess.run([tailscale_bin, "up", "--force"], check=False)
        else:
            log.warn("Please start Tailscale manually. Exiting module.")
            return

    ts_version = subprocess.run([tailscale_bin, "version"], capture_output=True, text=True).stdout.strip() or "unknown"
    log.info(f"Tailscale version: {ts_version}")

    try:
        ts_status_raw = subprocess.run([tailscale_bin, "status", "--json"], capture_output=True, text=True).stdout
        ts_status = json.loads(ts_status_raw)
    except Exception:
        ts_status = {}
        log.warn("Failed to read Tailscale status JSON")

    peers_raw = ts_status.get("Peer", [])
    peers = list(peers_raw.values()) if isinstance(peers_raw, dict) else peers_raw

    magic_dns_suffix = ts_status.get("MagicDNSSuffix", "ts.net")
    log.info(f"Tailnet MagicDNS suffix: {magic_dns_suffix}")

    ts_ip = ""
    self_ips = ts_status.get("Self", {}).get("TailscaleIPs", [])
    for ip in self_ips:
        if ip.startswith("100.") or ip.startswith("100.64"):
            ts_ip = ip
            break

    log.info(f"Detected Tailscale IP: {ts_ip}")

    reachable_devices = [
        (peer.get("HostName"), peer.get("DNSName", "").rstrip("."), ip)
        for peer in peers
        for ip in peer.get("TailscaleIPs", [])
        if peer.get("Online") and ip != ts_ip
    ]

    if not reachable_devices:
        log.info("No reachable tailnet devices found. Using placeholder example")
        reachable_devices = [("wolfcraig", "wolfcraig.ts.net", "")]

    for host, fqdn, ip in reachable_devices:
        if dry_run:
            log.info(f"[DRY-RUN] Would ping {host} ({ip})")
            continue
        ping_target = ip if ip else host
        ping_res = subprocess.run(
            [tailscale_bin, "ping", "--c", "1", ping_target],
            capture_output=True,
            text=True,
            check=False,
        )
        if ping_res.returncode == 0:
            log.success(f"Ping successful: {host} ({ip})")
        else:
            raw = (ping_res.stdout or ping_res.stderr).strip()
            detail = raw.splitlines()[0] if raw else "no output"
            log.warn(f"Ping failed: {host} ({ip}): {detail}")

        # DNS resolution via doggo using full MagicDNS FQDN from status JSON
        test_fqdn = fqdn or f"{host}.{magic_dns_suffix}"
        try:
            out = subprocess.run([doggo_bin, "query", test_fqdn], capture_output=True, text=True).stdout.strip()
            if out:
                log.success(f"DNS resolution success: {test_fqdn} -> {out}")
            else:
                log.warn(f"DNS resolution failed: {test_fqdn}")
        except Exception:
            log.warn(f"DNS resolution exception for {test_fqdn}")

    log.success("Tailscale module complete")

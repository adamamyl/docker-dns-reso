"""
dnsmasq.py
Module for dnsmasq configuration and status.
"""

import subprocess
from pathlib import Path

import modules.logger as logmod
from modules.install_utils import command_path, get_brew_prefix


DEFAULT_CONFIG = """\
listen-address=127.0.0.1
no-resolv
server=1.1.1.1
"""


def is_running(log=None):
    log = log or logmod.log
    res = subprocess.run(["pgrep", "-f", "dnsmasq"], capture_output=True, text=True)
    if res.stdout.strip():
        log.success("dnsmasq is running")
        return True
    else:
        log.warn("dnsmasq not running")
        return False


def create_config(
    cfg_path: str | None = None,
    content: str = DEFAULT_CONFIG,
    log=None,
    dry_run=False,
):
    log = log or logmod.log
    cfg_file = Path(cfg_path) if cfg_path else Path(get_brew_prefix()) / "etc" / "dnsmasq.conf"
    if dry_run:
        log.info(f"[DRY-RUN] Would write dnsmasq config to {cfg_file}")
        log.debug(f"Config content:\n{content}")
        return cfg_file

    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(content)
    log.success(f"dnsmasq config written to {cfg_file}")
    return cfg_file


def start_dnsmasq(log=None, dry_run=False):
    log = log or logmod.log
    dns_bin = command_path("dnsmasq")
    if dry_run:
        log.info(f"[DRY-RUN] Would start dnsmasq: {dns_bin}")
        return
    subprocess.Popen([dns_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.success("dnsmasq started")


# --- helpers for orchestrator ---
def ensure_config(log=None, dry_run=False):
    log = log or logmod.log
    return create_config(log=log, dry_run=dry_run)


def restart_service(log=None, dry_run=False):
    log = log or logmod.log
    if is_running(log=log):
        if dry_run:
            log.info("[DRY-RUN] Would stop existing dnsmasq")
        else:
            subprocess.run(["pkill", "-f", "dnsmasq"], check=False)
            log.info("dnsmasq stopped")
    start_dnsmasq(log=log, dry_run=dry_run)

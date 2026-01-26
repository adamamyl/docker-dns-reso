"""
dnsmasq.py
Module for dnsmasq configuration and status.
"""

import subprocess
from pathlib import Path
from . import logger
from .install_utils import command_path

DEFAULT_CONFIG = """\
listen-address=127.0.0.1
no-resolv
server=1.1.1.1
"""

def is_running(log=None):
    """
    Checks if dnsmasq process is running.
    Returns True if running, False otherwise.
    """
    log = log or logger.log
    dns_bin = command_path("dnsmasq")
    res = subprocess.run(["pgrep", "-f", "dnsmasq"], capture_output=True, text=True)
    if res.stdout.strip():
        log.success("dnsmasq is running")
        return True
    else:
        log.warning("dnsmasq not running")
        return False

def create_config(cfg_path: str = "/usr/local/etc/dnsmasq.conf", content: str = DEFAULT_CONFIG, log=None, dry_run=False):
    """
    Writes a dnsmasq config file.
    """
    log = log or logger.log
    cfg_file = Path(cfg_path)
    if dry_run:
        log.info(f"[DRY-RUN] Would write dnsmasq config to {cfg_file}")
        log.debug(f"Config content:\n{content}")
        return cfg_file

    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(content)
    log.success(f"dnsmasq config written to {cfg_file}")
    return cfg_file

def start_dnsmasq(log=None, dry_run=False):
    """
    Starts dnsmasq in the background.
    """
    log = log or logger.log
    dns_bin = command_path("dnsmasq")
    if dry_run:
        log.info(f"[DRY-RUN] Would start dnsmasq: {dns_bin}")
        return

    subprocess.Popen([dns_bin], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.success("dnsmasq started")

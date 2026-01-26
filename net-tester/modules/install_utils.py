# modules/install_utils.py
"""
Install/Utility module for net-tester

Provides functions to:
  - Check if common utilities/apps are installed
  - Get their versions
  - Optionally provide installation hints
"""

import shutil
import subprocess

from typing import List
from modules.logger import Logger
import modules.logger as logmod

def run_cmd(cmd_list: List[str], log: Logger, dry_run: bool = False) -> int:
    """
    Run a system command.
    
    :param cmd_list: Command as list of strings
    :param log: Logger instance
    :param dry_run: If True, do not actually execute
    :return: Return code of command
    """
    logmod.log.info(f"Running command: {' '.join(cmd_list)}")
    if dry_run:
        log.info("Dry run enabled, skipping execution")
        return 0
    try:
        result = subprocess.run(cmd_list, check=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        log.warning(f"Command failed: {e}")
        return e.returncode

def command_path(name: str) -> str:
    """Return full path of a command."""
    from shutil import which
    path = which(name)
    if path is None:
        raise FileNotFoundError(f"Command {name} not found")
    return path

def get_brew_prefix() -> str:
    """Return the Homebrew installation prefix for Intel or Apple Silicon macOS."""
    try:
        result = subprocess.run(
            ["brew", "--prefix"],
            capture_output=True,
            text=True,
            check=True
        )
        prefix = result.stdout.strip()
        if not prefix:
            raise RuntimeError("Brew returned empty prefix")
        return prefix
    except FileNotFoundError:
        raise RuntimeError("Homebrew is not installed or 'brew' is not in PATH")


# --- List of apps we care about ---
COMMON_APPS = {
    "docker": ["docker", "--version"],
    "tailscale": ["tailscale", "version"],
    "doggo": ["doggo", "--version"],
    "dnsmasq": ["dnsmasq", "--version"],
    "ip": ["ip", "-V"],  # iproute2mac on macOS
}

def command_exists(cmd_name: str) -> bool:
    """
    Check if a command exists in PATH.
    Returns True if found, False otherwise.
    """
    return shutil.which(cmd_name) is not None


def get_version(cmd_list) -> str:
    """
    Run a command list and return stdout as version string.
    Returns 'unknown' if fails.
    """
    try:
        result = subprocess.run(cmd_list, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def check_apps(apps=None) -> dict:
    """
    Check if apps are installed and get their versions.
    Returns a dict: {app_name: {"installed": bool, "version": str}}
    """
    apps = apps or COMMON_APPS
    results = {}

    for app, cmd_list in apps.items():
        installed = command_exists(cmd_list[0])
        version = get_version(cmd_list) if installed else None
        results[app] = {"installed": installed, "version": version}

        if installed:
            log.success(f"{app} installed, version: {version}")
        else:
            log.warning(f"{app} not found in PATH")

    return results


def install_hint(app_name: str) -> str:
    """
    Return a simple hint for installing a missing app.
    """
    hints = {
        "docker": "https://docs.docker.com/get-docker/",
        "tailscale": "https://tailscale.com/download",
        "doggo": "brew install doggo",
        "dnsmasq": "brew install dnsmasq",
        "ip": "brew install iproute2mac",
    }
    return hints.get(app_name, "No install hint available")

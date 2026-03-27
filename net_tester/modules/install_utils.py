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
import modules.logger as logmod

# [CURRENT]
def run_cmd(cmd_list: List[str], dry_run: bool = False, check: bool = True, capture_output: bool = True):
    """
    Run a system command.

    :param cmd_list: Command as list of strings
    :param dry_run: If True, do not actually execute (returns empty CompletedProcess)
    :param check: Whether to raise on non-zero exit
    :param capture_output: Whether to capture stdout/stderr
    :return: CompletedProcess instance
    """
    if dry_run:
        return subprocess.CompletedProcess(cmd_list, 0, stdout="", stderr="")
    return subprocess.run(cmd_list, check=check, capture_output=capture_output, text=True)

# [CURRENT]
def command_path(name: str):
    """Return full path of a command, or None if not found."""
    return shutil.which(name)

# [CURRENT]
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

# [CURRENT]
def command_exists(cmd_name: str) -> bool:
    """
    Check if a command exists in PATH.
    Returns True if found, False otherwise.
    """
    return shutil.which(cmd_name) is not None


# [CURRENT]
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


# [CURRENT]
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
            logmod.log.success(f"{app} installed, version: {version}")
        else:
            logmod.log.warn(f"{app} not found in PATH")

    return results


# [CURRENT]
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

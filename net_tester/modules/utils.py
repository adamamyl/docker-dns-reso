# modules/utils.py
import subprocess
from pathlib import Path


# [CURRENT]
def run_cmd(cmd, check=True, capture_output=True, text=True):
    """
    Simple wrapper around subprocess.run to mimic original expectation.
    Returns CompletedProcess object with stdout/stderr.
    """
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=text)


# [CURRENT]
def command_path(cmd_name: str):
    """Return absolute path to command or None"""
    from shutil import which

    return which(cmd_name)


# [CURRENT]
def get_brew_prefix():
    """Return Homebrew prefix or default /usr/local"""
    import subprocess

    try:
        return subprocess.run(
            ["brew", "--prefix"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "/usr/local"

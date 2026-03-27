"""
docker.py
Module for Docker-related checks and utilities.
"""

import subprocess

import modules.logger as logmod
from modules.install_utils import command_path


def is_running(log=None):
    """
    Check if the Docker daemon is running.
    Returns True if running, False otherwise.
    """
    log = log or logmod.log
    docker_bin = command_path("docker")
    if not docker_bin:
        log.error("Docker binary not found. Install Docker via Homebrew or official installer.")
        return False

    res = subprocess.run([docker_bin, "info"], capture_output=True, text=True, check=False)
    if res.returncode == 0:
        log.success("Docker daemon is running")
        return True
    else:
        log.warn("Docker daemon not running")
        return False


def wait_for_docker(timeout=45, log=None, dry_run=False):
    """
    Waits for the Docker daemon to start for up to `timeout` seconds.
    Returns True if daemon is running, False if timeout reached.
    """
    import time

    log = log or logmod.log

    if dry_run:
        log.info(f"[DRY-RUN] Would wait for Docker daemon for up to {timeout}s")
        return True

    log.info("⠹ Waiting for Docker daemon...")
    start = time.time()
    while time.time() - start < timeout:
        if is_running(log=log):
            return True
        time.sleep(1)
    log.warn(f"Docker daemon not running after {timeout}s timeout")
    return False

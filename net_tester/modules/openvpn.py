"""
openvpn.py — Check whether OpenVPN Connect is active and whether it affects .internal resolution.

OpenVPN Connect can push DNS settings through the tunnel that override /etc/resolver/ routing,
causing .internal domains to fail. This is the same class of bug as the Quad9 profile issue
(mDNSResponder treats VPN-pushed DNS as higher priority than /etc/resolver/ custom entries).

Specifically, if OpenVPN pushes a wildcard resolver (domain ~.) it intercepts ALL queries
before the /etc/resolver/internal → dnsmasq → 127.0.0.1 path is ever consulted.

Status matrix:
  warn  — OpenVPN Connect not installed (nothing to test)
  warn  — OpenVPN installed but no tunnel active (incomplete test — prompt user to connect and re-run)
  pass  — OpenVPN active + .internal resolves (VPN not interfering)
  fail  — OpenVPN active + .internal fails (VPN DNS is blocking .internal resolution)
  warn  — OpenVPN inactive + .internal fails (not VPN's fault)
"""

import socket
import subprocess
from pathlib import Path

from modules.install_utils import get_dnsmasq_fqdns, command_path
from modules.logger import Logger
from modules.types import CheckResult, Status

_OPENVPN_APP = Path("/Applications/OpenVPN Connect.app")


def run_checks(*, log: Logger, dry_run: bool = False) -> CheckResult:
    """Detect OpenVPN Connect status and test whether it affects .internal DNS resolution."""
    errors: list[str] = []

    test_domain = _pick_test_domain()
    installed = _detect_installed()
    tunnel_active = _detect_tunnel_active(dry_run=dry_run)
    dns_config, wildcard_vpn_dns = _get_vpn_dns_config(dry_run=dry_run)
    internal_resolves = _test_internal_resolution(test_domain) if not dry_run else True

    log.info(f"OpenVPN Connect installed: {installed}")
    log.info(f"VPN tunnel active: {tunnel_active}")
    log.info(f"Wildcard VPN DNS resolver (~.): {wildcard_vpn_dns}")
    log.info(f".internal resolution via getaddrinfo ({test_domain}): {internal_resolves}")

    status, summary = _determine_status(installed, tunnel_active, internal_resolves, wildcard_vpn_dns)

    return CheckResult(
        module="openvpn",
        status=status,
        summary=summary,
        details={
            "installed": installed,
            "tunnel_active": tunnel_active,
            "wildcard_vpn_dns": wildcard_vpn_dns,
            "internal_resolves": internal_resolves,
            "test_domain": test_domain,
            "vpn_dns_config": dns_config,
        },
        errors=errors,
    )


def _determine_status(
    installed: bool,
    tunnel_active: bool,
    internal_resolves: bool,
    wildcard_vpn_dns: bool,
) -> tuple[Status, str]:
    if not installed:
        return "warn", "OpenVPN Connect not installed — skipping VPN DNS interference check"
    if not tunnel_active:
        if not internal_resolves:
            return "warn", "OpenVPN inactive but .internal resolution broken — check other interference"
        return "warn", "OpenVPN installed but no tunnel active — connect and re-run to verify VPN DNS"
    if internal_resolves:
        return "pass", "OpenVPN tunnel active and .internal resolves correctly"
    if wildcard_vpn_dns:
        return "fail", "OpenVPN active with wildcard DNS (~.) blocking .internal resolution"
    return "fail", "OpenVPN active and .internal resolution broken"


def _pick_test_domain() -> str:
    """Return a real dnsmasq-known FQDN for a meaningful resolution test."""
    fqdns = get_dnsmasq_fqdns()
    return fqdns[0] if fqdns else "probe.internal"


def _detect_installed() -> bool:
    """Return True if OpenVPN Connect is installed as a macOS app or CLI binary."""
    return _OPENVPN_APP.exists() or command_path("openvpn") is not None


def _detect_tunnel_active(*, dry_run: bool) -> bool:
    """
    Return True if an OpenVPN tunnel is currently connected.

    Uses `scutil --nc list` which reports macOS VPN service connection state.
    A line containing both 'openvpn' (case-insensitive) and '(Connected)' means
    an active tunnel. The app process alone (menu bar icon, no connection) does not
    produce a Connected entry, avoiding the false-positive from pgrep matching the app.
    """
    if dry_run:
        return False
    scutil = command_path("scutil")
    if not scutil:
        return False
    result = subprocess.run([scutil, "--nc", "list"], capture_output=True, text=True, check=False)
    return any("(Connected)" in line and "openvpn" in line.lower() for line in result.stdout.splitlines())


def _get_vpn_dns_config(*, dry_run: bool) -> tuple[str, bool]:
    """
    Parse scutil --dns for VPN-pushed DNS resolvers.

    Returns (raw_output, wildcard_present) where wildcard_present is True if any resolver
    has domain '~.' — a wildcard catch-all that intercepts queries before /etc/resolver/.
    """
    if dry_run:
        return "", False
    scutil = command_path("scutil")
    if not scutil:
        return "", False
    result = subprocess.run([scutil, "--dns"], capture_output=True, text=True, check=False)
    output = result.stdout
    wildcard = any(line.strip().startswith("domain") and "~." in line for line in output.splitlines())
    return output, wildcard


def _test_internal_resolution(domain: str) -> bool:
    """
    Test .internal resolution via the system resolver (getaddrinfo).

    This is the exact path affected when VPN DNS overrides /etc/resolver/ routing.
    """
    try:
        return bool(socket.getaddrinfo(domain, None, socket.AF_INET))
    except (socket.gaierror, OSError):
        return False

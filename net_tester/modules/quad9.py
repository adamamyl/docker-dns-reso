"""
quad9.py — Regression test for the Quad9 profile / mDNSResponder interception bug.

The macOS 26 regression was triggered by having a Quad9 DNS configuration profile
installed. This module records:
  - Whether the Quad9 profile is currently installed
  - Whether Quad9 is reachable directly (confirming internet/DNS upstream health)
  - Whether .internal domains resolve correctly via getaddrinfo()

Status matrix:
  pass  — profile absent + .internal resolves  (current working state)
  pass  — profile present + .internal resolves (Apple/Quad9 fix confirmed!)
  fail  — profile present + .internal fails    (bug still active with profile)
  warn  — profile absent  + .internal fails    (broken, but not Quad9's fault)

Run this module periodically to detect when the fix lands without manual testing.
"""

import socket

from modules.install_utils import command_path, get_dnsmasq_fqdns, run_cmd
from modules.logger import Logger
from modules.types import CheckResult, Status

_QUAD9_KEYWORDS = frozenset({"Quad9", "quad9", "9.9.9.9", "149.112.112"})
_DIG_TIMEOUT = "3"  # passed to dig +time= to avoid long hangs


def run_checks(*, log: Logger, dry_run: bool = False) -> CheckResult:
    """Check Quad9 profile presence and test whether .internal resolution still works."""
    errors: list[str] = []

    # Use a real dnsmasq-known FQDN so getaddrinfo failure means the bug, not NXDOMAIN
    test_domain = _pick_test_domain()

    profile_installed, profile_lines = _detect_quad9_profile(dry_run=dry_run)
    quad9_reachable = _test_quad9_direct(dry_run=dry_run)
    internal_resolves = _test_internal_resolution(test_domain)

    log.info(f"Quad9 profile installed: {profile_installed}")
    log.info(f"Quad9 direct reachable (dig @9.9.9.9 google.com): {quad9_reachable}")
    log.info(f".internal resolution via getaddrinfo ({test_domain}): {internal_resolves}")

    status, summary = _determine_status(profile_installed, internal_resolves)

    return CheckResult(
        module="quad9",
        status=status,
        summary=summary,
        details={
            "profile_installed": profile_installed,
            "profile_matching_lines": profile_lines,
            "quad9_direct_reachable": quad9_reachable,
            "internal_resolves": internal_resolves,
            "test_domain": test_domain,
        },
        errors=errors,
    )


def _determine_status(profile_installed: bool, internal_resolves: bool) -> tuple[Status, str]:
    if profile_installed and internal_resolves:
        return "pass", "Quad9 profile present AND .internal resolves — fix appears to be working"
    if profile_installed and not internal_resolves:
        return "fail", "Quad9 profile installed and .internal resolution broken — mDNS interception bug still active"
    if not profile_installed and not internal_resolves:
        return "warn", "Quad9 profile absent but .internal resolution still broken — check other interference"
    return "pass", "Quad9 profile absent and .internal resolves correctly (expected baseline)"


def _pick_test_domain() -> str:
    """
    Return the first known dnsmasq FQDN for a meaningful resolution test.

    Using a real dnsmasq-known FQDN means getaddrinfo() failure = the mDNS interception
    bug, not a legitimate NXDOMAIN for an unknown host.
    Falls back to "probe.internal" if no dnsmasq config is found.
    """
    fqdns = get_dnsmasq_fqdns()
    return fqdns[0] if fqdns else "probe.internal"


def _detect_quad9_profile(*, dry_run: bool) -> tuple[bool, list[str]]:
    """Search system_profiler output for Quad9 DNS configuration profile entries."""
    if dry_run:
        return False, []
    sp = command_path("system_profiler")
    if not sp:
        return False, []
    result = run_cmd([sp, "SPConfigurationProfileDataType"], dry_run=False, check=False)
    matching = [line.strip() for line in result.stdout.splitlines() if any(kw in line for kw in _QUAD9_KEYWORDS)]
    return bool(matching), matching


def _test_quad9_direct(*, dry_run: bool) -> bool:
    """Confirm Quad9 is reachable by resolving google.com directly against 9.9.9.9."""
    if dry_run:
        return True
    dig = command_path("dig")
    if not dig:
        return False
    result = run_cmd(
        [dig, "@9.9.9.9", "google.com", "A", "+short", f"+time={_DIG_TIMEOUT}"],
        dry_run=False,
        check=False,
    )
    return bool(result.stdout.strip())


def _test_internal_resolution(domain: str) -> bool:
    """
    Test .internal resolution via the system resolver (getaddrinfo).

    This is the exact path that breaks when mDNSResponder intercepts the query.
    Returns True if any IPv4 address is returned, False on gaierror or empty result.
    """
    try:
        return bool(socket.getaddrinfo(domain, None, socket.AF_INET))
    except (socket.gaierror, OSError):
        return False

"""
mdns.py — Check for mDNS/mDNSResponder interference.

Examines three sources of potential interference:
  1. Installed configuration profiles — DNS-affecting profiles (e.g. Quad9) can
     cause mDNSResponder to intercept unicast queries for custom TLDs.
  2. /etc/hosts — custom entries bypass mDNSResponder but can shadow dnsmasq.
  3. mDNSResponder cache — probed via dns-sd; TTL 108002 + address 0.0.0.0
     confirms the interception fingerprint from the macOS 26 regression.
"""

import concurrent.futures
import functools
from pathlib import Path

from modules._dns_sd import probe as dns_sd_probe
from modules.install_utils import command_path, get_dnsmasq_fqdns, get_resolver_domains, run_cmd
from modules.logger import Logger
from modules.types import CheckResult, Status

_DNS_KEYWORDS = frozenset({"DNS", "nameserver", "resolver", "SearchDomains", "MatchDomains", "DNSSettings"})
_HOSTS_SKIP_PREFIXES = ("127.", "::1", "255.", "0.0.0.0", "fe80", "#")  # noqa: S104  # nosec B104 — comparison target, not a bind address


def run_checks(*, log: Logger, dry_run: bool = False, domains: list[str] | None = None) -> CheckResult:
    """Check profiles, /etc/hosts, and mDNS cache for DNS interference."""
    errors: list[str] = []

    if domains is None:
        domains = get_resolver_domains()

    profiles = _parse_config_profiles(dry_run=dry_run)
    hosts_custom = _parse_etc_hosts()
    dns_sd_results = _probe_all_domains(domains, log=log, dry_run=dry_run)
    intercepted = [r for r in dns_sd_results if r.get("intercepted")]

    log.info(f"Profiles with DNS keys: {len(profiles)}")
    log.info(f"Custom /etc/hosts entries: {len(hosts_custom)}")
    log.info(f"mDNS-intercepted domains: {len(intercepted)}/{len(dns_sd_results)}")

    status, summary = _determine_status(intercepted, profiles, hosts_custom, dns_sd_results)

    return CheckResult(
        module="mdns",
        status=status,
        summary=summary,
        details={
            "profiles_with_dns": profiles,
            "etc_hosts_custom": hosts_custom,
            "dns_sd_results": dns_sd_results,
            "intercepted_count": len(intercepted),
        },
        errors=errors,
    )


def _determine_status(
    intercepted: list[dict[str, object]],
    profiles: list[dict[str, str]],
    hosts_custom: list[str],
    dns_sd_results: list[dict[str, object]],
) -> tuple[Status, str]:
    if intercepted:
        return "fail", f"TTL-108002 mDNS intercept fingerprint on {len(intercepted)}/{len(dns_sd_results)} domain(s)"
    if profiles:
        return "warn", f"{len(profiles)} profile line(s) with DNS settings — may interfere with resolver"
    if hosts_custom:
        return "warn", f"{len(hosts_custom)} non-standard /etc/hosts entry(ies) detected"
    return "pass", "No mDNS interception, no conflicting profiles, no custom hosts entries"


def _parse_config_profiles(*, dry_run: bool) -> list[dict[str, str]]:
    """Scan system_profiler output for DNS-affecting configuration profile entries."""
    if dry_run:
        return []
    sp = command_path("system_profiler")
    if not sp:
        return []
    result = run_cmd([sp, "SPConfigurationProfileDataType"], dry_run=False, check=False)
    return _extract_dns_profile_entries(result.stdout)


def _extract_dns_profile_entries(output: str) -> list[dict[str, str]]:
    """Walk profile output; return entries whose lines contain DNS-related keywords."""
    entries: list[dict[str, str]] = []
    current_profile = ""
    for line in output.splitlines():
        stripped = line.strip()
        # Profile section headers end with ':' and are not list items
        if stripped.endswith(":") and not stripped.startswith("-"):
            current_profile = stripped.rstrip(":")
        for keyword in _DNS_KEYWORDS:
            if keyword in stripped:
                entries.append({"profile": current_profile, "line": stripped, "keyword": keyword})
                break
    return entries


def _parse_etc_hosts() -> list[str]:
    """Return non-standard /etc/hosts entries, skipping localhost, broadcast, and comments."""
    try:
        text = Path("/etc/hosts").read_text()
    except OSError:
        return []
    results: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in _HOSTS_SKIP_PREFIXES):
            continue
        results.append(stripped)
    return results


def _probe_all_domains(domains: list[str], *, log: Logger, dry_run: bool) -> list[dict[str, object]]:
    """
    Probe real dnsmasq FQDNs via dns-sd in parallel to detect mDNS interception.

    Uses actual address= entries (not synthetic probe.* names) so TTL-108002 + 0.0.0.0
    means mDNSResponder is intercepting a domain it should forward to dnsmasq.
    Runs all probes concurrently — each has a 2s timeout so sequential would be N×2s.
    """
    fqdns = get_dnsmasq_fqdns() or [f"probe.{d}" for d in domains]
    probe_fn = functools.partial(dns_sd_probe, timeout=2.0, dry_run=dry_run)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        results = list(pool.map(probe_fn, fqdns))
    for r, fqdn in zip(results, fqdns, strict=True):
        log.debug(f"dns-sd probe {fqdn}: intercepted={r.get('intercepted')}")
    return results

"""
resolver.py — Test the macOS /etc/resolver/ → dnsmasq → getaddrinfo chain.

Detects the macOS 26 mDNSResponder interception bug: dnsmasq answers correctly
when queried directly but getaddrinfo() returns nothing because mDNSResponder
intercepts the query and returns a cached "No Such Record" mDNS response with
TTL 108002 instead of forwarding to the unicast nameserver in /etc/resolver/.
"""

import socket

from modules._dns_sd import probe as dns_sd_probe
from modules.install_utils import command_path, get_dnsmasq_fqdns, get_resolver_domains, run_cmd
from modules.logger import Logger
from modules.types import CheckResult, DomainResult, Status


def run_checks(*, log: Logger, dry_run: bool = False) -> CheckResult:
    """Discover /etc/resolver/ domains and dnsmasq address= entries; probe all."""
    errors: list[str] = []

    resolver_domains = _read_resolver_domains()
    log.info(f"Found {len(resolver_domains)} /etc/resolver/ domain(s): {resolver_domains}")
    resolver_results = [_probe_domain(d, log=log, dry_run=dry_run) for d in resolver_domains]

    dnsmasq_results: list[DomainResult] = []
    try:
        dnsmasq_results = _probe_known_dnsmasq_domains(log=log, dry_run=dry_run)
        log.info(f"Probed {len(dnsmasq_results)} dnsmasq address= domain(s)")
    except Exception as exc:
        errors.append(f"dnsmasq domain probe failed: {exc}")

    all_results = resolver_results + dnsmasq_results
    diverged = [r for r in all_results if r["diverged"]]
    fingerprinted = [r for r in all_results if r["mdns_fingerprint"]]
    status, summary = _determine_status(all_results, diverged, fingerprinted, resolver_domains)

    return CheckResult(
        module="resolver",
        status=status,
        summary=summary,
        details={
            "resolver_domains": resolver_domains,
            "resolver_results": [dict(r) for r in resolver_results],
            "dnsmasq_results": [dict(r) for r in dnsmasq_results],
            "diverged_count": len(diverged),
            "fingerprinted_count": len(fingerprinted),
        },
        errors=errors,
    )


def _determine_status(
    all_results: list[DomainResult],
    diverged: list[DomainResult],
    fingerprinted: list[DomainResult],
    resolver_domains: list[str],
) -> tuple[Status, str]:
    if not resolver_domains:
        return "warn", "No /etc/resolver/ domains found — nothing to test"
    if not all_results:
        return "warn", "No domains probed"
    if diverged:
        suffix = " — mDNS intercept fingerprint confirmed" if fingerprinted else ""
        return "fail", f"{len(diverged)}/{len(all_results)} domain(s): dnsmasq OK, getaddrinfo FAIL{suffix}"
    return "pass", f"All {len(all_results)} domain(s) resolve correctly via both paths"


def _read_resolver_domains() -> list[str]:
    return get_resolver_domains()


def _probe_domain(domain: str, *, log: Logger, dry_run: bool) -> DomainResult:
    """Construct a synthetic probe FQDN from a resolver domain name and test resolution."""
    probe_fqdn = f"probe.{domain}"
    log.debug(f"Probing resolver domain via synthetic FQDN: {probe_fqdn}")
    return _resolve(probe_fqdn, log=log, dry_run=dry_run)


def _resolve(fqdn: str, *, log: Logger, dry_run: bool) -> DomainResult:
    """Run direct (dig @127.0.0.1) and system (getaddrinfo) resolution for one FQDN."""
    direct = _dig_direct(fqdn, dry_run=dry_run)
    system = _getaddrinfo(fqdn) if not dry_run else None
    fingerprint = dns_sd_probe(fqdn, timeout=2.0, dry_run=dry_run)
    diverged = direct is not None and system is None
    log.debug(f"  {fqdn}: direct={direct!r} system={system!r} diverged={diverged}")
    return DomainResult(
        domain=fqdn,
        direct_answer=direct,
        system_answer=system,
        diverged=diverged,
        mdns_fingerprint=bool(fingerprint.get("intercepted")),
    )


def _dig_direct(fqdn: str, *, dry_run: bool) -> str | None:
    """Query dnsmasq directly via dig @127.0.0.1. Returns first answer line or None."""
    dig = command_path("dig")
    if not dig or dry_run:
        return None
    result = run_cmd([dig, "@127.0.0.1", fqdn, "A", "+short"], dry_run=dry_run, check=False)
    lines = result.stdout.strip().splitlines()
    return lines[0] if lines else None


def _getaddrinfo(fqdn: str) -> str | None:
    """Resolve via the system resolver (exercises the mDNSResponder path). Returns first IPv4 or None."""
    try:
        infos = socket.getaddrinfo(fqdn, None, socket.AF_INET)
        return str(infos[0][4][0]) if infos else None
    except (socket.gaierror, OSError):
        return None


def _probe_known_dnsmasq_domains(*, log: Logger, dry_run: bool) -> list[DomainResult]:
    """Probe each FQDN from dnsmasq address= directives."""
    return [_resolve(fqdn, log=log, dry_run=dry_run) for fqdn in get_dnsmasq_fqdns()]

"""
docker_dns.py — Test DNS resolution from inside a Docker container.

Spins up a disposable Alpine container, installs bind-tools, and probes .internal
domain resolution via dig and getent. The container is always stopped on exit, even
if an exception is raised, via a try/finally block.

Detects the specific failure mode where the host's mDNS interception bug does not
affect container resolution (containers use Docker's embedded DNS at 127.0.0.11
which proxies through a different path), confirming whether the issue is host-only.
"""

import subprocess

from modules.install_utils import command_path, get_dnsmasq_fqdns, get_resolver_domains
from modules.logger import Logger
from modules.types import CheckResult

_ALPINE_IMAGE = "alpine:latest"
_CONTAINER_SLEEP = "120"
_INSTALL_TIMEOUT = 45
_DIG_TIMEOUT = 10


def run_checks(*, log: Logger, dry_run: bool = False, domains: list[str] | None = None) -> CheckResult:
    """Spin up an Alpine container, probe DNS for .internal domains, always clean up."""
    docker = command_path("docker")
    if not docker:
        return CheckResult(
            module="docker_dns",
            status="warn",
            summary="docker binary not found",
            details={},
            errors=[],
        )

    if domains is None:
        domains = get_resolver_domains() or ["internal"]

    if dry_run:
        log.info("[DRY-RUN] Would spin up Alpine container and probe DNS")
        return CheckResult(module="docker_dns", status="pass", summary="dry-run: skipped", details={}, errors=[])

    container_id: str | None = None
    errors: list[str] = []
    try:
        container_id = _start_container(docker, log=log)
        if not container_id:
            return CheckResult(
                module="docker_dns",
                status="warn",
                summary="Could not start Alpine container — Docker daemon may not be running",
                details={},
                errors=errors,
            )
        if not _install_bind_tools(docker, container_id, log=log):
            errors.append("bind-tools install failed — dig unavailable, using getent only")
        resolv_conf = _read_resolv_conf(docker, container_id)
        probe_results = _run_probes(docker, container_id, domains, log=log)
        return _build_result(probe_results, resolv_conf, errors)
    except Exception as exc:
        errors.append(repr(exc))
        return CheckResult(module="docker_dns", status="error", summary=str(exc), details={}, errors=errors)
    finally:
        if container_id:
            _stop_container(docker, container_id, log=log)


def _start_container(docker: str, *, log: Logger) -> str | None:
    """Start a detached Alpine container; return container ID or None on failure."""
    result = subprocess.run(
        [docker, "run", "-d", "--rm", _ALPINE_IMAGE, "sleep", _CONTAINER_SLEEP],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        log.warn(f"docker run failed: {result.stderr.strip()}")
        return None
    container_id = result.stdout.strip()
    log.debug(f"Started container: {container_id[:12]}")
    return container_id


def _install_bind_tools(docker: str, container_id: str, *, log: Logger) -> bool:
    """Install bind-tools (provides dig) inside the container via apk."""
    result = subprocess.run(
        [docker, "exec", container_id, "apk", "add", "--no-cache", "--quiet", "bind-tools"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_INSTALL_TIMEOUT,
    )
    if result.returncode != 0:
        log.warn("bind-tools install failed")
        return False
    log.debug("bind-tools installed in container")
    return True


def _exec_dig(docker: str, container_id: str, domain: str) -> str | None:
    """Run dig <domain> A +short inside the container. Returns first answer or None."""
    result = subprocess.run(
        [docker, "exec", container_id, "dig", domain, "A", "+short"],
        capture_output=True,
        text=True,
        check=False,
        timeout=_DIG_TIMEOUT,
    )
    lines = result.stdout.strip().splitlines()
    return lines[0] if lines else None


def _exec_getent(docker: str, container_id: str, domain: str) -> str | None:
    """Run getent hosts <domain> inside the container. Returns first IP or None."""
    result = subprocess.run(
        [docker, "exec", container_id, "getent", "hosts", domain],
        capture_output=True,
        text=True,
        check=False,
        timeout=_DIG_TIMEOUT,
    )
    parts = result.stdout.strip().split()
    return parts[0] if parts else None


def _read_resolv_conf(docker: str, container_id: str) -> str:
    """Read /etc/resolv.conf from inside the container."""
    result = subprocess.run(
        [docker, "exec", container_id, "cat", "/etc/resolv.conf"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _stop_container(docker: str, container_id: str, *, log: Logger) -> None:
    """Stop the container; best-effort, swallows all exceptions."""
    try:
        subprocess.run([docker, "stop", container_id], capture_output=True, check=False, timeout=10)
        log.debug(f"Stopped container: {container_id[:12]}")
    except Exception:
        pass


def _run_probes(docker: str, container_id: str, domains: list[str], *, log: Logger) -> list[dict[str, object]]:
    """
    Probe google.com as a baseline then real dnsmasq FQDNs from inside the container.

    Uses actual address= entries so that resolution failure means the bug, not NXDOMAIN.
    Falls back to synthetic probe.{domain} names if no dnsmasq config is found.
    """
    results: list[dict[str, object]] = []

    baseline_dig = _exec_dig(docker, container_id, "google.com")
    log.debug(f"Baseline google.com: {baseline_dig!r}")
    results.append({"domain": "google.com", "dig": baseline_dig, "getent": None, "is_baseline": True})

    fqdns = get_dnsmasq_fqdns() or [f"probe.{d}" for d in domains]
    for fqdn in fqdns:
        dig_result = _exec_dig(docker, container_id, fqdn)
        getent_result = _exec_getent(docker, container_id, fqdn)
        log.debug(f"  {fqdn}: dig={dig_result!r} getent={getent_result!r}")
        results.append({"domain": fqdn, "dig": dig_result, "getent": getent_result, "is_baseline": False})

    return results


def _build_result(
    probe_results: list[dict[str, object]],
    resolv_conf: str,
    errors: list[str],
) -> CheckResult:
    baseline = next((r for r in probe_results if r.get("is_baseline")), None)
    internal_probes = [r for r in probe_results if not r.get("is_baseline")]
    internal_failed = [r for r in internal_probes if not r.get("dig")]

    details: dict[str, object] = {"resolv_conf": resolv_conf, "probes": probe_results}

    if baseline and not baseline.get("dig"):
        return CheckResult(
            module="docker_dns",
            status="warn",
            errors=errors,
            details=details,
            summary="Baseline google.com failed — container DNS is broken entirely",
        )
    if internal_failed:
        n = f"{len(internal_failed)}/{len(internal_probes)}"
        return CheckResult(
            module="docker_dns",
            status="fail",
            errors=errors,
            details=details,
            summary=f"{n} internal domain(s) unresolvable from container",
        )
    return CheckResult(
        module="docker_dns",
        status="pass",
        errors=errors,
        details=details,
        summary=f"All {len(internal_probes)} internal domain(s) resolve correctly from container",
    )

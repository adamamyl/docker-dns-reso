"""
Internal helper: run dns-sd -G v4 with a timeout and detect the mDNS poison fingerprint.

Not intended for direct use by the coordinator — imported by resolver and mdns modules.

The poison fingerprint is TTL 108002 with address 0.0.0.0, which mDNSResponder emits
when it intercepts a unicast query and returns a synthetic "No Such Record" mDNS response
instead of forwarding to the configured nameserver in /etc/resolver/.
"""

import subprocess

from modules.install_utils import command_path

POISON_TTL = 108002
_MDNS_NO_SUCH_RECORD_ADDR = "0.0.0.0"  # noqa: S104  # nosec B104 — comparison target, not a bind address


def probe(domain: str, *, timeout: float = 2.0, dry_run: bool = False) -> dict[str, object]:
    """
    Run dns-sd -G v4 <domain> with a timeout and return the first meaningful result.

    Returns:
        domain      : the queried domain
        intercepted : True if TTL==108002 and address==0.0.0.0 (mDNS interception confirmed)
        ttl         : integer TTL from the response line, or None
        address     : IP address string from the response, or None
        raw         : raw output line (or full stdout if no line was parseable)
    """
    if dry_run:
        return {"domain": domain, "intercepted": False, "ttl": None, "address": None, "raw": ""}

    dns_sd = command_path("dns-sd")
    if not dns_sd:
        return {"domain": domain, "intercepted": False, "ttl": None, "address": None, "raw": "dns-sd not found"}

    stdout = _run_dns_sd(dns_sd, domain, timeout)

    for line in stdout.splitlines():
        parsed = _parse_dns_sd_line(line)
        if parsed is None:
            continue
        return {
            "domain": domain,
            "intercepted": parsed["ttl"] == POISON_TTL and parsed["address"] == _MDNS_NO_SUCH_RECORD_ADDR,
            "ttl": parsed["ttl"],
            "address": parsed["address"],
            "raw": line.strip(),
        }

    return {"domain": domain, "intercepted": False, "ttl": None, "address": None, "raw": stdout.strip()}


def _run_dns_sd(dns_sd: str, domain: str, timeout: float) -> str:
    """Launch dns-sd, collect output until timeout expires, then kill the process."""
    try:
        proc = subprocess.Popen(
            [dns_sd, "-G", "v4", domain],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
        return stdout
    except Exception as exc:
        return str(exc)


def _parse_dns_sd_line(line: str) -> dict[str, object] | None:
    """
    Parse one output line from dns-sd -G v4.

    Expected format: Timestamp A/R Flags IF Hostname Address TTL [notes...]
    Returns None for header lines, blank lines, or lines that don't match the format.
    """
    if not line.strip() or "Timestamp" in line or "STARTING" in line or line.startswith("DATE"):
        return None
    parts = line.split()
    if len(parts) < 7:
        return None
    try:
        ttl = int(parts[6])
    except ValueError:
        return None
    return {"ttl": ttl, "address": parts[5]}

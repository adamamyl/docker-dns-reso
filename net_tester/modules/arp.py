"""
arp.py — ARP table health and local-subnet reachability checks.

Detects the class of failure where same-subnet ARP is broken while routed
traffic still works — a pattern caused by:
  - macOS pre-release networking regressions (e.g. Tahoe 26.x alpha)
  - WiFi AP multicast/broadcast filtering (e.g. Multicast-to-Unicast on UniFi)
  - VPN or endpoint-security system extensions intercepting outbound packets

Checks:
  1. macOS build type — warns on alpha/beta builds known to regress networking
  2. ARP table health — counts incomplete entries on the local subnet
  3. Same-subnet vs routed reachability — TCP probe to distinguish L2 failure
     from a general network outage
  4. Active system extensions — flags network/security extensions that can
     intercept or drop packets (NordVPN Shield, Tailscale, Bitdefender, etc.)
"""

import platform
import re
import socket
from typing import Any

from modules.install_utils import run_cmd
from modules.logger import Logger
from modules.types import CheckResult, Status

# System extensions whose presence alongside connectivity issues is worth flagging.
_KNOWN_INTERFERING_BUNDLES = (
    "com.nordvpn",
    "io.tailscale",
    "com.bitdefender",
    "com.cisco",
    "com.paloaltonetworks",
    "com.sophos",
    "com.crowdstrike",
    "com.sentinelone",
    "com.mullvad",
)

# Timeout in seconds for TCP reachability probes.
_TCP_TIMEOUT = 2.0

# Ports tried in order when probing a host for reachability.
_PROBE_PORTS = (443, 80, 22, 5001, 5000)


def run_checks(*, log: Logger, dry_run: bool = False) -> CheckResult:
    errors: list[str] = []
    details: dict[str, Any] = {}
    issues: list[str] = []

    # 1. macOS build type
    build_info = _check_macos_build()
    details["macos_build"] = build_info
    if build_info.get("prerelease"):
        issues.append(f"macOS pre-release build ({build_info['version']}) — known to regress networking")
        log.warn(f"macOS pre-release: {build_info['version']} ({build_info['build']})")

    # 2. ARP table health
    try:
        arp_info = _check_arp_table(log=log, dry_run=dry_run)
        details["arp"] = arp_info
        if arp_info["incomplete_same_subnet"] > 0:
            issues.append(
                f"{arp_info['incomplete_same_subnet']} incomplete ARP "
                f"entry/entries on local subnet ({arp_info['local_subnet']})"
            )
        log.info(
            f"ARP: {arp_info['complete_same_subnet']} complete, "
            f"{arp_info['incomplete_same_subnet']} incomplete on subnet"
        )
    except Exception as exc:
        errors.append(f"ARP table check failed: {exc}")

    # 3. Same-subnet vs routed reachability
    try:
        reach = _check_reachability(log=log, dry_run=dry_run)
        details["reachability"] = reach
        if reach.get("l2_broken"):
            issues.append(
                "Same-subnet TCP probes fail while routed traffic works — "
                "likely WiFi→wired ARP filtering or macOS L2 regression"
            )
            log.warn("L2 broken: same-subnet unreachable, routed traffic OK")
        elif reach.get("same_subnet_reachable") is False and reach.get("routed_reachable") is False:
            issues.append("Both same-subnet and routed traffic unreachable — general network outage")
    except Exception as exc:
        errors.append(f"Reachability check failed: {exc}")

    # 4. System extensions
    try:
        ext_info = _check_system_extensions(log=log, dry_run=dry_run)
        details["system_extensions"] = ext_info
        if ext_info["active_interfering"]:
            names = ", ".join(ext_info["active_interfering"])
            issues.append(f"Active network/security extension(s) may intercept traffic: {names}")
            log.warn(f"Interfering extensions: {names}")
        log.info(f"System extensions: {len(ext_info['all_active'])} active")
    except Exception as exc:
        errors.append(f"System extension check failed: {exc}")

    status = _determine_status(issues, details)
    summary = "; ".join(issues) if issues else "ARP healthy, subnet reachable, no interfering extensions"
    return CheckResult(module="arp", status=status, summary=summary, details=details, errors=errors)


def _determine_status(issues: list[str], details: dict[str, Any]) -> Status:
    if not issues:
        return "pass"
    reach = details.get("reachability", {})
    if reach.get("l2_broken"):
        return "fail"
    arp = details.get("arp", {})
    if arp.get("incomplete_same_subnet", 0) > 0 and arp.get("complete_same_subnet", 0) == 0:
        return "fail"
    return "warn"


# ---------------------------------------------------------------------------
# macOS build
# ---------------------------------------------------------------------------


def _check_macos_build() -> dict[str, Any]:
    """Return macOS version info; flag alpha (a) / beta (b) builds."""
    mac_ver = platform.mac_ver()[0]  # e.g. "26.3.1"
    build = ""
    extra = ""
    try:
        result = run_cmd(["sw_vers"], dry_run=False, check=False)
        for line in result.stdout.splitlines():
            if "ProductVersionExtra" in line:
                extra = line.split(":", 1)[1].strip().strip("()")
            if "BuildVersion" in line:
                build = line.split(":", 1)[1].strip()
    except Exception:  # nosec B110 — sw_vers unavailable; fall back to empty strings
        pass
    prerelease = extra.lower() in ("a", "b", "alpha", "beta") or build.endswith("a") or build.endswith("b")
    return {
        "version": mac_ver,
        "build": build,
        "extra": extra,
        "prerelease": prerelease,
    }


# ---------------------------------------------------------------------------
# ARP table
# ---------------------------------------------------------------------------

_ARP_LINE_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",  # neighbour linklayer expire_o expire_i netif
)


def _check_arp_table(*, log: Logger, dry_run: bool) -> dict[str, Any]:
    """Parse `arp -a -l` and report complete vs incomplete entries on the local subnet."""
    local_ip, local_subnet = _get_local_subnet()
    log.debug(f"Local subnet: {local_subnet}, IP: {local_ip}")

    result = run_cmd(["arp", "-a", "-l"], dry_run=dry_run, check=False)
    complete: list[str] = []
    incomplete: list[str] = []

    for line in result.stdout.splitlines():
        if not _is_same_subnet(line, local_subnet):
            continue
        if "(incomplete)" in line or "link#" in line.split()[1] if len(line.split()) > 1 else False:
            incomplete.append(line.strip())
        elif re.search(r"([0-9a-f]{1,2}:){5}[0-9a-f]{1,2}", line, re.IGNORECASE):
            complete.append(line.strip())

    return {
        "local_ip": local_ip,
        "local_subnet": local_subnet,
        "complete_same_subnet": len(complete),
        "incomplete_same_subnet": len(incomplete),
        "complete_entries": complete,
        "incomplete_entries": incomplete,
    }


def _get_local_subnet() -> tuple[str, str]:
    """Return (local_ip, subnet_prefix) for the primary non-loopback IPv4 interface."""
    try:
        result = run_cmd(["ifconfig"], dry_run=False, check=False)
        for line in result.stdout.splitlines():
            if "inet " in line and "127." not in line:
                parts = line.strip().split()
                ip_idx = parts.index("inet") + 1
                mask_idx = parts.index("netmask") + 1 if "netmask" in parts else -1
                ip = parts[ip_idx]
                if mask_idx > 0:
                    mask_hex = parts[mask_idx]
                    prefix = _hex_mask_to_prefix(mask_hex)
                    subnet = _ip_to_subnet(ip, prefix)
                    return ip, subnet
    except Exception:  # nosec B110 — ifconfig unavailable; caller handles empty return
        pass
    return "", ""


def _hex_mask_to_prefix(hex_mask: str) -> int:
    """Convert hex netmask (e.g. 0xffffff00) to prefix length (e.g. 24)."""
    try:
        n = int(hex_mask, 16)
        return bin(n).count("1")
    except ValueError:
        return 24


def _ip_to_subnet(ip: str, prefix: int) -> str:
    """Return subnet in CIDR notation for a given IP and prefix."""
    try:
        parts = [int(p) for p in ip.split(".")]
        mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
        net = [(parts[i] & ((mask >> (24 - 8 * i)) & 0xFF)) for i in range(4)]
        return f"{'.'.join(str(o) for o in net)}/{prefix}"
    except Exception:
        return ""


def _is_same_subnet(arp_line: str, subnet: str) -> bool:
    """Check if an ARP line's IP falls within subnet."""
    if not subnet:
        return False
    m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", arp_line)
    if not m:
        return False
    try:
        ip_parts = [int(p) for p in m.group(1).split(".")]
        net_str, prefix_str = subnet.split("/")
        net_parts = [int(p) for p in net_str.split(".")]
        prefix = int(prefix_str)
        mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF

        def to_int(parts: list[int]) -> int:
            return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]

        return (to_int(ip_parts) & mask) == (to_int(net_parts) & mask)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------


def _check_reachability(*, log: Logger, dry_run: bool) -> dict[str, Any]:
    """
    Probe same-subnet hosts and the default gateway via TCP.

    If same-subnet probes all fail but the gateway probe succeeds, we have
    an L2 (ARP/WiFi bridging) issue rather than a general outage.
    """
    if dry_run:
        return {"dry_run": True}

    gateway = _get_default_gateway()
    same_subnet_hosts = _get_same_subnet_hosts_from_arp()

    gateway_reachable = _tcp_probe(gateway, log=log) if gateway else None
    same_subnet_results: dict[str, bool] = {}
    for host in same_subnet_hosts[:5]:  # limit probes
        same_subnet_results[host] = _tcp_probe(host, log=log)

    same_subnet_reachable = any(same_subnet_results.values()) if same_subnet_results else None
    l2_broken = gateway_reachable is True and same_subnet_reachable is False and bool(same_subnet_results)

    log.debug(f"Gateway {gateway}: {gateway_reachable}, same-subnet: {same_subnet_results}")

    return {
        "gateway": gateway,
        "gateway_reachable": gateway_reachable,
        "same_subnet_hosts_probed": same_subnet_results,
        "same_subnet_reachable": same_subnet_reachable,
        "l2_broken": l2_broken,
    }


def _get_default_gateway() -> str:
    """Return the default gateway IP from `netstat -rn`."""
    try:
        result = run_cmd(["netstat", "-rn", "-f", "inet"], dry_run=False, check=False)
        for line in result.stdout.splitlines():
            if line.startswith("default"):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
    except Exception:  # nosec B110 — netstat unavailable; caller handles empty return
        pass
    return ""


def _get_same_subnet_hosts_from_arp() -> list[str]:
    """Return IPs of hosts with complete ARP entries on the local subnet (excluding self/broadcast)."""
    local_ip, local_subnet = _get_local_subnet()
    if not local_subnet:
        return []
    try:
        result = run_cmd(["arp", "-a", "-l"], dry_run=False, check=False)
        hosts: list[str] = []
        for line in result.stdout.splitlines():
            if "(incomplete)" in line:
                continue
            if "ff:ff:ff:ff:ff:ff" in line:
                continue
            if not _is_same_subnet(line, local_subnet):
                continue
            m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
            if m and m.group(1) != local_ip:
                hosts.append(m.group(1))
        return hosts
    except Exception:
        return []


def _tcp_probe(host: str, *, log: Logger) -> bool:
    """Try TCP connect to host on common ports; return True if any succeed."""
    for port in _PROBE_PORTS:
        try:
            with socket.create_connection((host, port), timeout=_TCP_TIMEOUT):
                log.debug(f"TCP probe {host}:{port} succeeded")
                return True
        except OSError:
            continue
    log.debug(f"TCP probe {host} failed on all ports {_PROBE_PORTS}")
    return False


# ---------------------------------------------------------------------------
# System extensions
# ---------------------------------------------------------------------------


def _check_system_extensions(*, log: Logger, dry_run: bool) -> dict[str, Any]:
    """List active system extensions; flag those known to interfere with networking."""
    if dry_run:
        return {"dry_run": True, "all_active": [], "active_interfering": []}

    result = run_cmd(["systemextensionsctl", "list"], dry_run=False, check=False)
    all_active: list[str] = []
    interfering: list[str] = []

    for line in result.stdout.splitlines():
        # Active extensions have '* *' at the start of the line
        if not line.strip().startswith("*"):
            continue
        # Extract bundle ID (e.g. io.tailscale.ipn.macsys.network-extension)
        m = re.search(r"([\w.-]+\.[\w.-]+)\s+\(", line)
        if not m:
            continue
        bundle_id = m.group(1)
        all_active.append(bundle_id)
        if any(bundle_id.startswith(known) for known in _KNOWN_INTERFERING_BUNDLES):
            interfering.append(bundle_id)
            log.debug(f"Flagged extension: {bundle_id}")

    return {
        "all_active": all_active,
        "active_interfering": interfering,
    }

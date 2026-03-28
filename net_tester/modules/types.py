"""Shared types for net-tester diagnostic modules."""

from typing import Literal, TypedDict

Status = Literal["pass", "fail", "warn", "skip", "error"]


class DomainResult(TypedDict):
    domain: str
    direct_answer: str | None  # dig @127.0.0.1 result
    system_answer: str | None  # socket.getaddrinfo result
    diverged: bool  # direct resolves but system does not (mDNS interception indicator)
    mdns_fingerprint: bool  # TTL-108002 "No Such Record" detected via dns-sd


class CheckResult(TypedDict):
    module: str
    status: Status
    summary: str
    details: dict[str, object]
    errors: list[str]

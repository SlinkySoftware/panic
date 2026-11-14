"""Trusted Reverse Proxy Client-IP Extraction Engine (T-S3-03)."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

DEFAULT_TRUSTED_PROXY_CIDRS: tuple[str, ...] = ("127.0.0.1/32", "::1/128")


class ClientIpResolution(BaseModel):
    """Result of resolving the effective connecting client IP address."""

    client_ip: str
    remote_addr: str
    trusted_proxy: bool
    header_used: str | None = None
    proxy_chain: list[str] = Field(default_factory=list)


def is_ip_in_cidrs(ip_str: str, cidrs: Sequence[str]) -> bool:
    """Return True if ``ip_str`` is a valid IP contained within any network in ``cidrs``."""
    try:
        addr = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False

    for raw_cidr in cidrs:
        cleaned = raw_cidr.strip()
        if not cleaned:
            continue
        try:
            net = ipaddress.ip_network(cleaned, strict=False)
        except ValueError:
            continue
        if addr.version == net.version and addr in net:
            return True
    return False


def _extract_header_value(headers: Mapping[str, str] | None, header_name: str) -> str | None:
    """Look up ``header_name`` case-insensitively in HTTP headers or Django META dict."""
    if not headers:
        return None
    target = header_name.strip()
    if not target:
        return None

    if target.upper().startswith("HTTP_"):
        canonical_http = target[5:].replace("_", "-").lower()
        meta_key = target.upper()
    else:
        canonical_http = target.replace("_", "-").lower()
        meta_key = "HTTP_" + target.upper().replace("-", "_")

    for key, val in headers.items():
        if val is None:
            continue
        if key.lower().replace("_", "-") == canonical_http or key.upper() == meta_key:
            return str(val)
    return None


def resolve_client_ip(
    remote_addr: str,
    headers: Mapping[str, str] | None = None,
    *,
    trust_proxy_headers: bool = True,
    trusted_proxy_cidrs: Sequence[str] | None = None,
    proxy_ip_header: str = "X-Forwarded-For",
) -> ClientIpResolution:
    """Resolve the true client IP address with anti-spoofing trusted-proxy verification.

    Forwarded headers are only inspected when ``trust_proxy_headers`` is True AND
    ``remote_addr`` belongs to ``trusted_proxy_cidrs``. When trusted, ``proxy_ip_header``
    is parsed right-to-left and the right-most untrusted IP is returned.
    """
    raw_remote = (remote_addr or "").strip()
    try:
        clean_remote = str(ipaddress.ip_address(raw_remote))
    except ValueError:
        clean_remote = "127.0.0.1"

    effective_cidrs: Sequence[str] = (
        DEFAULT_TRUSTED_PROXY_CIDRS if trusted_proxy_cidrs is None else trusted_proxy_cidrs
    )

    if not trust_proxy_headers or not is_ip_in_cidrs(clean_remote, effective_cidrs):
        return ClientIpResolution(
            client_ip=clean_remote,
            remote_addr=clean_remote,
            trusted_proxy=False,
            header_used=None,
            proxy_chain=[],
        )

    raw_header = _extract_header_value(headers, proxy_ip_header)
    proxy_chain: list[str] = []
    if raw_header:
        for part in raw_header.split(","):
            token = part.strip()
            if not token:
                continue
            try:
                addr = ipaddress.ip_address(token)
                proxy_chain.append(str(addr))
            except ValueError:
                continue

    if not proxy_chain:
        return ClientIpResolution(
            client_ip=clean_remote,
            remote_addr=clean_remote,
            trusted_proxy=True,
            header_used=None,
            proxy_chain=[],
        )

    selected_ip = proxy_chain[0]
    for candidate in reversed(proxy_chain):
        if not is_ip_in_cidrs(candidate, effective_cidrs):
            selected_ip = candidate
            break

    return ClientIpResolution(
        client_ip=selected_ip,
        remote_addr=clean_remote,
        trusted_proxy=True,
        header_used=proxy_ip_header,
        proxy_chain=proxy_chain,
    )

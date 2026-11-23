"""Trusted Reverse Proxy Client-IP Extraction Engine."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from typing import Literal

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


# ---------------------------------------------------------------------------
# Hardened X-Forwarded-For / Forwarded chain resolution (ARCHITECTURE §5, AR-5.3).
# ---------------------------------------------------------------------------

ChainDecision = Literal[
    "HEADERS_DISABLED",
    "UNTRUSTED_PEER",
    "NO_HEADER",
    "FIRST_UNTRUSTED_HOP",
    "ALL_HOPS_TRUSTED",
    "MALFORMED_HOP",
]

#: Outcomes where the true client location is unknown, so the caller assigns the Default zone.
UNKNOWN_LOCATION_DECISIONS: frozenset[ChainDecision] = frozenset(
    {"UNTRUSTED_PEER", "NO_HEADER", "ALL_HOPS_TRUSTED", "MALFORMED_HOP"}
)


class ChainHop(BaseModel):
    """One entry of the resolved hop list, ordered right (peer) to left."""

    position: int
    ip: str
    source: Literal["peer", "header"]
    trusted: bool
    selected: bool = False


class ChainResolution(BaseModel):
    """Result of :func:`resolve_client_chain` (API.md §6 `GET /api/v1/admin/client-ip` shape)."""

    remote_addr: str
    peer_trusted: bool
    header_used: str | None = None
    hops: list[ChainHop] = Field(default_factory=list)
    ignored_left_hops: int = 0
    truncated: bool = False
    decision: ChainDecision
    client_ip: str
    location_known: bool


class ProxyChainConfig(BaseModel):
    """`PANIC_TRUST_PROXY_HEADERS` / `PANIC_TRUSTED_PROXY_CIDRS` / `PANIC_PROXY_IP_HEADER` /
    `PANIC_UNTRUSTED_PEER_POLICY` / `PANIC_XFF_MAX_HOPS` / `PANIC_XFF_MAX_BYTES` (AR-5.2/5.3).

    ``untrusted_peer_policy`` is carried here for the caller's convenience; this pure function
    only reports facts (``decision``) and never raises — applying ``reject`` (403) is the
    caller's job (middleware / context).
    """

    trust_proxy_headers: bool = True
    trusted_proxy_cidrs: tuple[str, ...] = DEFAULT_TRUSTED_PROXY_CIDRS
    proxy_ip_header: Literal["X-Forwarded-For", "Forwarded"] = "X-Forwarded-For"
    untrusted_peer_policy: Literal["default", "reject"] = "default"
    max_hops: int = 16
    max_bytes: int = 4096


def _clean_ip(raw: str) -> str:
    cleaned = (raw or "").strip()
    try:
        return str(ipaddress.ip_address(cleaned))
    except ValueError:
        return "127.0.0.1"


def _parse_hop_token(token: str) -> str | None:
    """Parse one XFF-style or bare `for=` value into a normalised IP, or None if unparseable."""
    candidate = token.strip()
    if not candidate or candidate.lower() == "unknown":
        return None
    if candidate.startswith('"') and candidate.endswith('"') and len(candidate) >= 2:
        candidate = candidate[1:-1]
    if candidate.startswith("["):
        end = candidate.find("]")
        if end == -1:
            return None
        candidate = candidate[1:end]
    elif candidate.count(":") == 1:
        host_part, _, port_part = candidate.rpartition(":")
        if port_part.isdigit():
            candidate = host_part
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return str(addr)


def _parse_forwarded_element(element: str) -> str | None:
    """Extract and parse the `for=` parameter of one RFC 7239 `Forwarded` element."""
    for part in element.split(";"):
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "for":
            return _parse_hop_token(value)
    return None


def resolve_client_chain(
    peer: str,
    headers: Mapping[str, str] | None = None,
    config: ProxyChainConfig | None = None,
) -> ChainResolution:
    """Resolve the true client IP by walking the hop chain right to left (AR-5.3).

    Pure and side-effect free: it never raises and never looks anything up. Every
    unknown-location outcome (see :data:`UNKNOWN_LOCATION_DECISIONS`) is flagged
    ``location_known=False`` so the caller assigns the Default zone.
    """
    cfg = config or ProxyChainConfig()
    clean_peer = _clean_ip(peer)

    if not cfg.trust_proxy_headers:
        return ChainResolution(
            remote_addr=clean_peer,
            peer_trusted=is_ip_in_cidrs(clean_peer, cfg.trusted_proxy_cidrs),
            header_used=None,
            hops=[],
            ignored_left_hops=0,
            truncated=False,
            decision="HEADERS_DISABLED",
            client_ip=clean_peer,
            location_known=True,
        )

    peer_trusted = is_ip_in_cidrs(clean_peer, cfg.trusted_proxy_cidrs)
    if not peer_trusted:
        return ChainResolution(
            remote_addr=clean_peer,
            peer_trusted=False,
            header_used=None,
            hops=[],
            ignored_left_hops=0,
            truncated=False,
            decision="UNTRUSTED_PEER",
            client_ip=clean_peer,
            location_known=False,
        )

    raw_header = _extract_header_value(headers, cfg.proxy_ip_header)
    if not raw_header or not raw_header.strip():
        return ChainResolution(
            remote_addr=clean_peer,
            peer_trusted=True,
            header_used=None,
            hops=[ChainHop(position=1, ip=clean_peer, source="peer", trusted=True, selected=True)],
            ignored_left_hops=0,
            truncated=False,
            decision="NO_HEADER",
            client_ip=clean_peer,
            location_known=False,
        )

    truncated = False
    header_bytes = raw_header.encode("utf-8", "ignore")
    if len(header_bytes) > cfg.max_bytes:
        raw_header = header_bytes[-cfg.max_bytes :].decode("utf-8", "ignore")
        truncated = True

    raw_tokens = raw_header.split(",")
    parser = _parse_forwarded_element if cfg.proxy_ip_header == "Forwarded" else _parse_hop_token
    parsed: list[str | None] = [parser(tok) for tok in raw_tokens]

    if len(parsed) > cfg.max_hops:
        parsed = parsed[-cfg.max_hops :]
        truncated = True

    total = len(parsed)
    examined: list[tuple[str, bool]] = []  # right-to-left order: (ip, trusted)
    looked_at = 0
    decision: ChainDecision = "ALL_HOPS_TRUSTED"

    for idx in range(total - 1, -1, -1):
        looked_at += 1
        ip = parsed[idx]
        if ip is None:
            decision = "MALFORMED_HOP"
            break
        trusted = is_ip_in_cidrs(ip, cfg.trusted_proxy_cidrs)
        examined.append((ip, trusted))
        if not trusted:
            decision = "FIRST_UNTRUSTED_HOP"
            break
    else:
        decision = "ALL_HOPS_TRUSTED"

    if decision == "FIRST_UNTRUSTED_HOP":
        client_ip = examined[-1][0]
        location_known = True
    else:
        # ALL_HOPS_TRUSTED or MALFORMED_HOP: location unknown; record the last trusted hop
        # (or the peer, if no header hop was trusted before the walk stopped).
        client_ip = examined[-1][0] if examined else clean_peer
        location_known = False

    ordered: list[tuple[Literal["peer", "header"], str, bool]] = [("peer", clean_peer, True)]
    ordered.extend(("header", ip, trusted) for ip, trusted in examined)
    n = len(ordered)
    hops = [
        ChainHop(
            position=n - i,
            ip=ip,
            source=source,
            trusted=trusted,
            selected=(i == n - 1),
        )
        for i, (source, ip, trusted) in enumerate(ordered)
    ]

    return ChainResolution(
        remote_addr=clean_peer,
        peer_trusted=True,
        header_used=cfg.proxy_ip_header,
        hops=hops,
        ignored_left_hops=total - looked_at,
        truncated=truncated,
        decision=decision,
        client_ip=client_ip,
        location_known=location_known,
    )

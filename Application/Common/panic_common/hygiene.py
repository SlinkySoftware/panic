"""Normalization & Deduplication Engine and Credential Hygiene Validator (SPEC §4.3, AR-2.1)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from panic_common.models import EXCLUSIVE_PROTOCOLS, PROTOCOL_ORDER, CatalogItem, Connection, Protocol

DEFAULT_PORTS: dict[Protocol, int] = {
    Protocol.URL: 443,
    Protocol.SSH: 22,
    Protocol.RDP: 3389,
    Protocol.LOCAL_APP: 443,
}

# Patterns that indicate embedded credentials or plaintext password flags
_USERINFO_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")
_HOST_USERPASS_RE = re.compile(r"^[^/\s:@]+:[^/\s@]+@")
_PASSWORD_FLAGS_RE = re.compile(
    r"(?:^|\s)(?:-pw|--password|--pass|-p\s+\S*pass\S*|sshpass\b|password=|passwd=|secret=)",
    re.IGNORECASE,
)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)


class SharePreviewResult(BaseModel):
    normalized_keys: list[str]
    resolved_host: str
    resolved_port: int
    hygiene_passed: bool
    hygiene_errors: list[str] = Field(default_factory=list)
    duplicate_found: bool = False
    existing_item: CatalogItem | None = None


def resolve_default_port(protocol: Protocol, port: int | None, scheme: str = "") -> int:
    if port is not None and port > 0:
        return port
    if protocol == Protocol.URL and scheme.lower() == "http":
        return 80
    return DEFAULT_PORTS.get(protocol, 443)


def normalize_target(
    protocol: Protocol,
    host: str,
    port: int | None = None,
    path_or_args: str = "",
) -> tuple[str, str, int]:
    """Compute a deterministic ``normalized_key`` for deduplication (SPEC §4.3).

    Lowercases hostnames, strips trailing URL slashes, and resolves default ports
    (80/443 for URL, 22 for SSH, 3389 for RDP).
    Returns ``(normalized_key, clean_host, resolved_port)``.
    """
    raw_host = host.strip()
    raw_path = path_or_args.strip()
    scheme = "https"

    if protocol == Protocol.URL and raw_host.lower().startswith(("http://", "https://")):
        parsed = urlsplit(raw_host)
        scheme = (parsed.scheme or "https").lower()
        hostname = (parsed.hostname or raw_host).lower().strip(".")
        effective_port = parsed.port or resolve_default_port(protocol, port, scheme)
        url_path = parsed.path or raw_path or ""
        clean_path = url_path.rstrip("/")
        key = f"{protocol.value.lower()}://{hostname}:{effective_port}{clean_path}"
        return key, hostname, effective_port

    if "://" in raw_host:
        parsed = urlsplit(raw_host)
        hostname = (parsed.hostname or raw_host).lower().strip(".")
        effective_port = parsed.port or resolve_default_port(protocol, port, parsed.scheme)
    else:
        # Handle host:port if user typed port inline
        if ":" in raw_host and not raw_host.startswith("["):
            host_part, _, port_part = raw_host.rpartition(":")
            if port_part.isdigit():
                raw_host = host_part
                if port is None:
                    port = int(port_part)
        hostname = raw_host.lower().strip().strip(".")
        effective_port = resolve_default_port(protocol, port, scheme)

    if protocol == Protocol.LOCAL_APP and port is None and ":" not in raw_host:
        clean_cmd = raw_host.strip()
        cmd_key = f"{clean_cmd} {raw_path}".strip().lower()
        return f"local_app://{cmd_key}", clean_cmd, 0

    if protocol == Protocol.URL:
        clean_path = ("/" + raw_path.lstrip("/")).rstrip("/") if raw_path else ""
        key = f"url://{hostname}:{effective_port}{clean_path}"
    else:
        key = f"{protocol.value.lower()}://{hostname}:{effective_port}"

    return key, hostname, effective_port


def check_connections(connections: list[Connection]) -> list[str]:
    """Errors in the protocol mix itself: at least one, each at most once, never SSH with RDP."""
    protocols = [c.protocol for c in connections]
    if not protocols:
        return ["Select at least one protocol."]
    errors: list[str] = []
    if len(set(protocols)) != len(protocols):
        errors.append("Each protocol may appear only once.")
    if set(protocols) >= EXCLUSIVE_PROTOCOLS:
        errors.append("An item may have SSH or RDP, not both.")
    return errors


def normalize_connections(host: str, connections: list[Connection]) -> tuple[list[str], str, list[Connection]]:
    """``(normalized_keys, clean_host, connections)`` for a whole item, connections in ``PROTOCOL_ORDER``.

    A URL typed into the host (``https://portal:8443/ui``) is reduced to its hostname; its port and
    path move into the URL connection unless that connection already sets them.
    """
    ordered = sorted(connections, key=lambda c: PROTOCOL_ORDER.index(c.protocol))
    raw_host = host.strip()
    if raw_host.lower().startswith(("http://", "https://")):
        parsed = urlsplit(raw_host)
        ordered = [
            c.model_copy(
                update={
                    "port": c.port if c.port is not None else parsed.port,
                    "path_or_args": c.path_or_args or parsed.path.rstrip("/"),
                }
            )
            if c.protocol == Protocol.URL
            else c
            for c in ordered
        ]
        raw_host = (parsed.hostname or raw_host).lower().strip(".")
    keys: list[str] = []
    clean_host = raw_host
    for i, c in enumerate(ordered):
        key, hostname, _port = normalize_target(c.protocol, raw_host, c.port, c.path_or_args)
        keys.append(key)
        if i == 0:
            clean_host = hostname
    return keys, clean_host, ordered


def check_credential_hygiene(
    protocol: Protocol,
    host: str,
    path_or_args: str = "",
    account_override: str = "",
    custom_uri: str = "",
) -> list[str]:
    """Inspect candidate endpoint fields and return hygiene violation messages (SPEC §4.3, AR-2.1)."""
    errors: list[str] = []
    combined_fields = [host, path_or_args, account_override, custom_uri]

    if _USERINFO_RE.search(host.strip()) or _HOST_USERPASS_RE.search(host.strip()):
        errors.append("Embedded credentials (user:password@host) are forbidden in target host or URL fields.")

    if custom_uri and (_USERINFO_RE.search(custom_uri.strip()) or _HOST_USERPASS_RE.search(custom_uri.strip())):
        errors.append("Embedded credentials (user:password@host) are forbidden in custom URI fields.")

    if ":" in account_override or " " in account_override.strip():
        errors.append("Account override may only specify a username or domain\\username, never a password or CLI flag.")

    for text in combined_fields:
        if _PASSWORD_FLAGS_RE.search(text):
            errors.append(
                "Plaintext password flags (-pw, --password, sshpass, password=) are forbidden in catalog items."
            )
            break

    for text in combined_fields:
        if _PRIVATE_KEY_RE.search(text):
            errors.append("Embedded SSH/TLS private key material is strictly prohibited.")
            break

    return errors


def check_item_hygiene(host: str, account_override: str, connections: list[Connection]) -> list[str]:
    """``check_credential_hygiene`` over every connection of one item, each message reported once."""
    errors: list[str] = []
    for c in connections or [Connection(protocol=Protocol.SSH)]:
        for e in check_credential_hygiene(c.protocol, host, c.path_or_args, account_override, c.custom_uri):
            if e not in errors:
                errors.append(e)
    return errors


def preview_catalog_submission(
    host: str,
    connections: list[Connection],
    account_override: str,
    existing_catalog: list[CatalogItem],
) -> SharePreviewResult:
    """Run normalization, deduplication check, and credential hygiene validation."""
    normalized_keys, clean_host, ordered = normalize_connections(host, connections)
    _key, _host, resolved_port = normalize_target(ordered[0].protocol, clean_host, ordered[0].port)
    hygiene_errors = check_item_hygiene(host, account_override, ordered)
    duplicate: CatalogItem | None = None
    for item in existing_catalog:
        if set(item.normalized_keys) & set(normalized_keys):
            duplicate = item
            break

    return SharePreviewResult(
        normalized_keys=normalized_keys,
        resolved_host=clean_host,
        resolved_port=resolved_port,
        hygiene_passed=len(hygiene_errors) == 0,
        hygiene_errors=hygiene_errors,
        duplicate_found=duplicate is not None,
        existing_item=duplicate,
    )

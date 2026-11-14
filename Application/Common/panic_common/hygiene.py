"""Normalization & Deduplication Engine and Credential Hygiene Validator (SPEC §4.3, AR-2.1)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from panic_common.models import CatalogItem, Protocol

DEFAULT_PORTS: dict[Protocol, int] = {
    Protocol.WEB: 443,
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
    normalized_key: str
    resolved_host: str
    resolved_port: int
    hygiene_passed: bool
    hygiene_errors: list[str] = Field(default_factory=list)
    duplicate_found: bool = False
    existing_item: CatalogItem | None = None


def resolve_default_port(protocol: Protocol, port: int | None, scheme: str = "") -> int:
    if port is not None and port > 0:
        return port
    if protocol == Protocol.WEB and scheme.lower() == "http":
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
    (80/443 for WEB, 22 for SSH, 3389 for RDP).
    Returns ``(normalized_key, clean_host, resolved_port)``.
    """
    raw_host = host.strip()
    raw_path = path_or_args.strip()
    scheme = "https"

    if protocol == Protocol.WEB and raw_host.lower().startswith(("http://", "https://")):
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

    if protocol == Protocol.WEB:
        clean_path = ("/" + raw_path.lstrip("/")).rstrip("/") if raw_path else ""
        key = f"web://{hostname}:{effective_port}{clean_path}"
    else:
        key = f"{protocol.value.lower()}://{hostname}:{effective_port}"

    return key, hostname, effective_port


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
        errors.append(
            "Embedded credentials (user:password@host) are forbidden in target host or URL fields."
        )

    if custom_uri and (_USERINFO_RE.search(custom_uri.strip()) or _HOST_USERPASS_RE.search(custom_uri.strip())):
        errors.append("Embedded credentials (user:password@host) are forbidden in custom URI fields.")

    if ":" in account_override or " " in account_override.strip():
        errors.append(
            "Account override may only specify a username or domain\\username, never a password or CLI flag."
        )

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


def preview_catalog_submission(
    protocol: Protocol,
    host: str,
    port: int | None,
    path_or_args: str,
    account_override: str,
    custom_uri: str,
    existing_catalog: list[CatalogItem],
) -> SharePreviewResult:
    """Run normalization, deduplication check, and credential hygiene validation."""
    normalized_key, clean_host, resolved_port = normalize_target(protocol, host, port, path_or_args)
    hygiene_errors = check_credential_hygiene(
        protocol=protocol,
        host=host,
        path_or_args=path_or_args,
        account_override=account_override,
        custom_uri=custom_uri,
    )
    duplicate: CatalogItem | None = None
    for item in existing_catalog:
        if item.normalized_key == normalized_key:
            duplicate = item
            break

    return SharePreviewResult(
        normalized_key=normalized_key,
        resolved_host=clean_host,
        resolved_port=resolved_port,
        hygiene_passed=len(hygiene_errors) == 0,
        hygiene_errors=hygiene_errors,
        duplicate_found=duplicate is not None,
        existing_item=duplicate,
    )

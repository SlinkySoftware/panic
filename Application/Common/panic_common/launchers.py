"""Zero-Install Session Launchers & Strict Parameter Sanitization (SPEC §4.2, §5.2, AR-2.2, AR-2.3)."""

from __future__ import annotations

import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")


def sanitize_launch_param(value: str) -> str:
    """Strip CR, LF, NUL, and control characters to prevent .rdp directive injection and CLI newline injection."""
    return _CONTROL_CHARS_RE.sub("", value).strip()


def interpolate_ssh_command(
    template: str,
    host: str,
    port: int | None,
    user: str,
    flags: str = "",
) -> str:
    """Interpolate ``{host}``, ``{port}``, ``{user}``, and ``{flags}`` into the user's SSH template."""
    safe_template = sanitize_launch_param(template) or "ssh {user}@{host} -p {port} {flags}"
    safe_host = sanitize_launch_param(host)
    safe_port = str(port if port and port > 0 else 22)
    safe_user = sanitize_launch_param(user) or "operator"
    safe_flags = sanitize_launch_param(flags)

    rendered = (
        safe_template.replace("{host}", safe_host)
        .replace("{port}", safe_port)
        .replace("{user}", safe_user)
        .replace("{flags}", safe_flags)
    )
    # Collapse redundant trailing/multiple spaces when {flags} is empty
    return re.sub(r"\s{2,}", " ", rendered).strip()


def interpolate_local_app_command(
    template: str,
    host: str,
    port: int | None,
    user: str,
) -> str:
    """Interpolate ``{host}``, ``{port}``, and ``{user}`` into a LOCAL_APP command template."""
    safe_template = sanitize_launch_param(template)
    safe_host = sanitize_launch_param(host)
    safe_port = str(port if port and port > 0 else 443)
    safe_user = sanitize_launch_param(user) or "operator"

    rendered = (
        safe_template.replace("{host}", safe_host)
        .replace("{port}", safe_port)
        .replace("{user}", safe_user)
    )
    return re.sub(r"\s{2,}", " ", rendered).strip()


def generate_rdp_content(
    host: str,
    port: int | None = 3389,
    username: str = "",
    title: str = "",
    extra_properties: str = "",
) -> str:
    """Generate an ephemeral plain-text .rdp file payload with strict parameter sanitization (SPEC §4.2, §5.2)."""
    safe_host = sanitize_launch_param(host)
    effective_port = port if port and port > 0 else 3389
    safe_user = sanitize_launch_param(username)
    safe_title = sanitize_launch_param(title)

    lines = [
        f"full address:s:{safe_host}:{effective_port}",
        "prompt for credentials:i:1",
        "administrative session:i:1",
        "screen mode id:i:2",
        "desktopwidth:i:1920",
        "desktopheight:i:1080",
        "session bpp:i:32",
        "compression:i:1",
        "keyboardhook:i:2",
        "audiocapturemode:i:0",
        "videoplaybackmode:i:1",
        "connection type:i:7",
        "networkautodetect:i:1",
        "bandwidthautodetect:i:1",
        "enableworkspacereconnect:i:0",
        "redirectclipboard:i:1",
        "redirectprinters:i:0",
        "redirectcomports:i:0",
        "redirectsmartcards:i:1",
        "negotiate security layer:i:1",
        "remoteapplicationmode:i:0",
    ]
    if safe_user:
        lines.insert(1, f"username:s:{safe_user}")
    if safe_title:
        lines.append(f"shell working directory:s:{safe_title}")

    if extra_properties:
        # Allow safe key:type:value lines only
        for raw_line in extra_properties.splitlines():
            clean_line = sanitize_launch_param(raw_line)
            if clean_line and re.match(r"^[a-zA-Z0-9 _-]+:[isb]:[^;\r\n]+$", clean_line):
                lines.append(clean_line)

    return "\r\n".join(lines) + "\r\n"

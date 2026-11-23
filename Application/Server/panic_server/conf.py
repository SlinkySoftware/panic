"""Settings helpers: every setting comes from the environment (AR-3.1).

Secrets may also be supplied as ``<NAME>_FILE`` pointing to a file (Docker secrets). The ``_FILE``
variant wins when both are set.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def env(name: str, default: str | None = None) -> str | None:
    """Return ``$NAME`` (or the content of ``$NAME_FILE``), else ``default``."""
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        try:
            return Path(file_path).expanduser().read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ImproperlyConfigured(f"{name}_FILE is set but cannot be read: {e.strerror}") from e
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def env_str(name: str, default: str) -> str:
    value = env(name, default)
    return default if value is None else value


def env_bool(name: str, default: bool) -> bool:
    value = env(name)
    if value is None:
        return default
    v = value.lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean (true/false), got {value!r}")


def env_int(name: str, default: int) -> int:
    value = env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as e:
        raise ImproperlyConfigured(f"{name} must be an integer, got {value!r}") from e


def env_list(name: str, default: str = "") -> list[str]:
    value = env(name, default) or ""
    return [item.strip() for item in value.split(",") if item.strip()]

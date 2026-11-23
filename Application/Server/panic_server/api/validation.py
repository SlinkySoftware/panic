"""Tiny shared request-body validation helper: turns a missing required field into a
proper ``400 VALIDATION_ERROR`` (API.md §3) instead of an uncaught ``KeyError`` -> 500.
"""

from __future__ import annotations

from typing import Any

from panic_common.errors import ErrorCode
from panic_server.api.errors import ApiError


def require(body: dict[str, Any], *names: str) -> None:
    """Raise ``400 VALIDATION_ERROR`` (with per-field ``fields``) if any of ``names`` is missing,
    ``None``, or an empty string in ``body``."""
    missing = [n for n in names if body.get(n) in (None, "")]
    if missing:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"Missing required field(s): {', '.join(missing)}.",
            status_code=400,
            fields={n: ["This field is required."] for n in missing},
        )


__all__ = ["require"]

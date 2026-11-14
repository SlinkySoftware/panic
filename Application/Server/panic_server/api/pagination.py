"""Reusable paging envelopes (API.md §1). No endpoint in T-S6-06 is paged (search is a flat,
capped list; bootstrap/dashboard views are single resources) -- this module is built now, as a
required owned file, purely as infra for T-S6-07's table (catalog/lists/users) and audit list
endpoints, which import it directly rather than reinventing paging envelopes twice.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


class PageEnvelopePagination(PageNumberPagination):
    """``?page=&page_size=`` -> ``{"results", "page", "page_size", "total", "has_next"}``."""

    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE
    page_query_param = "page"

    def get_paginated_response(self, data: list[Any]) -> Response:
        return Response(
            {
                "results": data,
                "page": self.page.number,
                "page_size": self.page.paginator.per_page,
                "total": self.page.paginator.count,
                "has_next": self.page.has_next(),
            }
        )


def encode_cursor(value: dict[str, Any]) -> str:
    """Opaque keyset cursor: base64url of a small JSON object (e.g. ``{"created_at": ..., "id": ...}``)."""
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any] | None:
    """The inverse of :func:`encode_cursor`; ``None`` for a missing/malformed cursor (never raises)."""
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        value = json.loads(decoded)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class KeysetPage:
    """A page of keyset-paginated ``results`` plus the opaque cursor for the next page (or ``None``)."""

    results: list[Any]
    next_cursor: str | None

    def envelope(self) -> dict[str, Any]:
        return {"results": self.results, "next_cursor": self.next_cursor}


def keyset_params(request: Request, *, default_limit: int, max_limit: int) -> tuple[int, dict[str, Any] | None]:
    """``(limit, cursor)`` parsed from ``?limit=&cursor=``, clamped to ``max_limit``."""
    try:
        limit = int(request.query_params.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    limit = max(1, min(limit, max_limit))
    cursor = decode_cursor(request.query_params.get("cursor", ""))
    return limit, cursor


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "KeysetPage",
    "PageEnvelopePagination",
    "decode_cursor",
    "encode_cursor",
    "keyset_params",
]

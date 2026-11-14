"""Weak ``ETag``/``If-None-Match`` support for UI view endpoints (API.md §2).

The hash covers zone, View As and preference effects "automatically" per the spec, simply by
hashing the exact response body the view was about to send -- the body already reflects all of
that (it was built from the caller's own ``RequestContext``), so there is nothing extra to fold
in here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.http import HttpRequest
from rest_framework.response import Response


def weak_etag(body: dict[str, Any]) -> str:
    """``W/"<first 16 hex chars of sha256>"`` of ``body``'s canonical JSON encoding."""
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f'W/"{digest}"'


def if_none_match_satisfied(request: HttpRequest, etag: str) -> bool:
    header = request.headers.get("If-None-Match", "")
    if not header:
        return False
    candidates = {c.strip() for c in header.split(",")}
    return "*" in candidates or etag in candidates


def etag_response(request: HttpRequest, body: dict[str, Any]) -> Response:
    """A 200 (with ``body`` and ``ETag``) or, on a matching ``If-None-Match``, an empty 304."""
    etag = weak_etag(body)
    response = Response(status=304) if if_none_match_satisfied(request, etag) else Response(body)
    response["ETag"] = etag
    response["Cache-Control"] = "no-cache"
    return response


__all__ = ["etag_response", "if_none_match_satisfied", "weak_etag"]

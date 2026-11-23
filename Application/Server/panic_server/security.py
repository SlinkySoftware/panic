"""Security headers, Mongo-backed rate limiting, and JSON-aware CSRF failure handling."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from panic_common.errors import ErrorCode
from panic_server.store.rate_limits import increment

DEFAULT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityHeadersMiddleware:
    """Attach CSP, ``nosniff``, ``Referrer-Policy`` and ``Permissions-Policy`` to every response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", getattr(settings, "PANIC_CSP", "") or DEFAULT_CSP)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response


def parse_rate(rate: str) -> tuple[int, int]:
    """Parse ``"<count>/<seconds>"`` (e.g. ``"10/60"``)."""
    count, _, window = rate.partition("/")
    return max(1, int(count)), max(1, int(window or "60"))


#: The legacy ``/login`` path (no longer routed) and ``/api/v1/auth/login`` (API.md §4.1) bucket
#: identically. ``/auth/oidc/login`` is GET-only in practice, so it never
#: actually reaches here (``_STATE_CHANGING`` already filtered to POST/PUT/PATCH/DELETE above);
#: it is kept for the same reason the old entry was: harmless, future-proof against a GET-only
#: assumption changing.
_LOGIN_PATHS = frozenset({"/login", "/auth/oidc/login", "/api/v1/auth/login"})


def _bucket(request: HttpRequest) -> str | None:
    if request.method not in _STATE_CHANGING:
        return None
    if request.path_info in _LOGIN_PATHS:
        return "login"
    if request.path_info.startswith("/api/"):
        return "api"
    return None


def _client_ip(request: HttpRequest) -> str:
    return getattr(request, "client_ip", None) or request.META.get("REMOTE_ADDR", "unknown")


def _login_username(request: HttpRequest) -> str | None:
    """Best-effort submitted username, for the ``login:user`` bucket (DATA_MODEL.md §4.12).

    ``/login``'s form POST populates ``request.POST`` directly; ``/api/v1/auth/login`` is a DRF
    view that only ever receives a JSON body (no form-encoded fallback), so ``request.POST`` is
    always empty there -- fall back to parsing ``request.body`` as JSON. ``request.body`` is read
    *first* and only then ``request.POST`` -- the other way round, Django's own multipart/form
    parser (triggered by ``.POST``) consumes the raw stream, and a later ``.body`` access raises
    ``RawPostDataException``. Reading ``.body`` first caches the raw bytes, so both this and DRF's
    own later parsing of the same request still work.
    """
    body = request.body
    username = request.POST.get("username", "").strip()
    if username:
        return username
    if body:
        try:
            data = json.loads(body)
        except ValueError:
            return None
        if isinstance(data, dict):
            value = data.get("username")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _retry_after(window_s: int) -> int:
    """Seconds remaining in the current fixed window starting now (``rate_limits.increment``'s window)."""
    epoch = int(dt.datetime.now(dt.UTC).timestamp())
    remaining = window_s - (epoch % window_s)
    return remaining if remaining > 0 else window_s


def _rate_limited(window_s: int) -> JsonResponse:
    response = JsonResponse(
        {"error_code": ErrorCode.RATE_LIMITED, "detail": "Too many requests; slow down."}, status=429
    )
    response["Retry-After"] = str(_retry_after(window_s))
    return response


class RateLimitMiddleware:
    """Per-client-IP (and, for ``/login``, per-username) fixed-window limits (DATA_MODEL.md §4.12).

    Counters live in Mongo's ``rate_limits`` collection (``panic_server.store.rate_limits``), so
    every worker/node shares the same counts -- no local-memory cache, no ``PANIC_CACHE_URL``.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        bucket = _bucket(request) if settings.PANIC_RATE_LIMIT_ENABLED else None
        if bucket is None:
            return self.get_response(request)

        client = _client_ip(request)
        if bucket == "login":
            limit, window = parse_rate(settings.PANIC_RATE_LIMIT_LOGIN)
            over = increment("login:ip", client, window) > limit
            username = _login_username(request)
            if username:
                over = increment("login:user", username, window) > limit or over
        else:
            limit, window = parse_rate(settings.PANIC_RATE_LIMIT_API)
            over = increment("api:ip", client, window) > limit

        if over:
            return _rate_limited(window)
        return self.get_response(request)


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """``CSRF_FAILURE_VIEW``: JSON for API clients, plain page for browsers."""
    if request.path_info.startswith("/api/"):
        return JsonResponse(
            {"error_code": ErrorCode.CSRF_FAILED, "detail": "CSRF token missing or invalid. Reload the page."},
            status=403,
        )
    return HttpResponse(
        "Forbidden: the form has expired or the CSRF token is invalid. Go back, reload, and try again.",
        content_type="text/plain; charset=utf-8",
        status=403,
    )

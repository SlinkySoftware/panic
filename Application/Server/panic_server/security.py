"""Security headers, rate limiting, and JSON-aware CSRF failure handling (T-S3-04)."""

from __future__ import annotations

import time
from collections.abc import Callable

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse

from panic_common.errors import ErrorCode

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


def _bucket(request: HttpRequest) -> str | None:
    if request.method not in _STATE_CHANGING:
        return None
    if request.path in {"/login", "/auth/oidc/login"}:
        return "login"
    if request.path.startswith("/api/"):
        return "api"
    return None


def hit(bucket: str, key: str, rate: str) -> tuple[bool, int]:
    """Count one request in a fixed window. Returns ``(allowed, retry_after_seconds)``."""
    limit, window = parse_rate(rate)
    now = int(time.time())
    window_start = now - (now % window)
    cache_key = f"panic:rl:{bucket}:{key}:{window_start}"
    cache.add(cache_key, 0, timeout=window + 1)
    try:
        count = cache.incr(cache_key)
    except ValueError:  # evicted between add() and incr()
        cache.set(cache_key, 1, timeout=window + 1)
        count = 1
    return count <= limit, window_start + window - now


class RateLimitMiddleware:
    """Per-client-IP fixed-window limits on ``/login`` and state-changing ``/api/*`` requests.

    Counters live in the Django cache (local memory per process by default; configure a shared
    cache via ``PANIC_CACHE_URL`` for multi-worker deployments).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        bucket = _bucket(request) if settings.PANIC_RATE_LIMIT_ENABLED else None
        if bucket is not None:
            rate = settings.PANIC_RATE_LIMIT_LOGIN if bucket == "login" else settings.PANIC_RATE_LIMIT_API
            client = getattr(request, "client_ip", None) or request.META.get("REMOTE_ADDR", "unknown")
            allowed, retry_after = hit(bucket, str(client), rate)
            if not allowed:
                response = JsonResponse(
                    {"error_code": ErrorCode.RATE_LIMITED, "detail": "Too many requests; slow down."}, status=429
                )
                response["Retry-After"] = str(max(1, retry_after))
                return response
        return self.get_response(request)


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """``CSRF_FAILURE_VIEW``: JSON for API clients, plain page for browsers."""
    if request.path.startswith("/api/"):
        return JsonResponse(
            {"error_code": ErrorCode.CSRF_FAILED, "detail": "CSRF token missing or invalid. Reload the page."},
            status=403,
        )
    return HttpResponse(
        "Forbidden: the form has expired or the CSRF token is invalid. Go back, reload, and try again.",
        content_type="text/plain; charset=utf-8",
        status=403,
    )

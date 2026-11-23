"""Request-ID propagation, access log, Prometheus metrics, and per-request context resolution."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse
from prometheus_client import Counter, Histogram

from panic_common.errors import ErrorCode
from panic_server.context import UntrustedPeerRejected, build_request_context
from panic_server.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
CLIENT_IP_HEADER = "X-Client-IP"
SECURITY_ZONE_HEADER = "X-Security-Zone"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")

access_log = logging.getLogger("panic_server.access")

HTTP_REQUESTS = Counter(
    "panic_http_requests_total", "HTTP requests handled by PANIC Server", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "panic_http_request_duration_seconds", "HTTP request latency in seconds", ["method", "route"]
)


def _route_of(request: HttpRequest) -> str:
    match = getattr(request, "resolver_match", None)
    if match is None:
        return "unmatched"
    return match.route or match.view_name or "unknown"


class RequestIdMiddleware:
    """Accept or generate ``X-Request-ID``, expose it to logging, echo it in the response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            elapsed = time.perf_counter() - started
            response[REQUEST_ID_HEADER] = request_id
            route = _route_of(request)
            HTTP_REQUESTS.labels(request.method or "GET", route, str(response.status_code)).inc()
            HTTP_LATENCY.labels(request.method or "GET", route).observe(elapsed)
            if route != "metrics":
                access_log.info(
                    "%s %s %s",
                    request.method,
                    request.path,
                    response.status_code,
                    extra={
                        "method": request.method,
                        "path": request.path,
                        "status": response.status_code,
                        "duration_ms": round(elapsed * 1000, 1),
                    },
                )
            return response
        finally:
            request_id_var.reset(token)


class RequestContextMiddleware:
    """Resolve :class:`panic_server.context.RequestContext` once per request.

    There is no store-wide lock or simulator concept: identity always comes from a real
    session, and the zone always comes from the real client IP (AR-5.3/ADR-0001 decision 6).
    Downstream code reads ``request.context``; ``request.client_ip``
    and ``request.resolved_zone`` are kept as convenience aliases some tests/call sites expect.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            context = build_request_context(request)
        except UntrustedPeerRejected:
            response = JsonResponse(
                {"error_code": ErrorCode.UNTRUSTED_PEER, "detail": "Untrusted reverse-proxy peer"},
                status=403,
            )
            response[REQUEST_ID_HEADER] = getattr(request, "request_id", "")
            return response

        request.context = context
        request.client_ip = context.client_ip
        request.resolved_zone = context.zone

        response = self.get_response(request)
        # Kept for backward compatibility (cheap; the full diagnostics are GET /api/v1/admin/client-ip).
        response[CLIENT_IP_HEADER] = context.client_ip
        response[SECURITY_ZONE_HEADER] = context.zone.id if context.zone else "UNZONED"
        return response

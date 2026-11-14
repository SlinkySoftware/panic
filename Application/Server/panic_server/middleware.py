"""Request-ID propagation, access log, Prometheus metrics, and Client-IP / Security Zone middleware."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from prometheus_client import Counter, Histogram

from panic_common.proxy import resolve_client_ip
from panic_common.zones import resolve_ip_zone
from panic_server.logging import request_id_var
from panic_server.state import STORE

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


class ClientIpZoneMiddleware:
    """Resolve effective client IP (trusted reverse-proxy aware) and Security Zone on every request."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        remote_addr = request.META.get("REMOTE_ADDR", "127.0.0.1")
        trust_proxy_headers = bool(getattr(settings, "PANIC_TRUST_PROXY_HEADERS", True))
        trusted_proxy_cidrs = getattr(settings, "PANIC_TRUSTED_PROXY_CIDRS", ["127.0.0.1/32", "::1/128"])
        proxy_ip_header = str(getattr(settings, "PANIC_PROXY_IP_HEADER", "X-Forwarded-For"))

        ip_res = resolve_client_ip(
            remote_addr=remote_addr,
            headers=request.headers,
            trust_proxy_headers=trust_proxy_headers,
            trusted_proxy_cidrs=trusted_proxy_cidrs,
            proxy_ip_header=proxy_ip_header,
        )
        zone_res = resolve_ip_zone(ip_res.client_ip, STORE.zones)

        request.client_ip = ip_res.client_ip
        request.client_ip_resolution = ip_res
        request.resolved_zone = zone_res.winning_zone
        request.zone_resolution = zone_res

        response = self.get_response(request)
        response[CLIENT_IP_HEADER] = ip_res.client_ip
        response[SECURITY_ZONE_HEADER] = zone_res.winning_zone.id if zone_res.winning_zone else "UNZONED"
        return response

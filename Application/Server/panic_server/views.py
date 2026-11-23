"""Health, version and Prometheus metrics endpoints.

Everything else under ``/api/v1/*`` is the DRF API in ``panic_server.api`` (see ``urls.py``).
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from panic_server import __version__
from panic_server.store import client as store_client


def health_view(request: HttpRequest) -> JsonResponse:
    """Liveness by default; ``?ready=1`` additionally pings Mongo (readiness, AR-3.3, API.md §4.8).

    Plain liveness (no ``?ready=1``) never touches Mongo: it only reports that the process is up,
    so it stays fast and meaningful even when Mongo itself is the thing that is down.
    """
    if request.GET.get("ready") != "1":
        return JsonResponse({"status": "ok", "component": "panic-server"})
    ok, error = store_client.ping()
    return JsonResponse(
        {
            "status": "ok" if ok else "error",
            "component": "panic-server",
            "mongo": "ok" if ok else (error or "error"),
        },
        status=200 if ok else 503,
    )


def version_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"name": "panic-server", "version": __version__})


def metrics_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)

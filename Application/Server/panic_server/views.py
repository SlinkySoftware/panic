"""Health, version and Prometheus metrics endpoints (T-S6-04).

Every other Stage 1-5 view here was STORE-coupled (the server-rendered UI shell, and the whole
``/api/v1/*`` CRUD surface for dashboards/catalog/lists/sites/teams/zones/rbac/audit/export/the
.rdp launcher) and is deleted along with ``STORE``/``state.py``/``store_db.py``. That surface is
rebuilt against the new DRF/Mongo stack by T-S6-06/07 (see ``urls.py``'s module docstring).
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

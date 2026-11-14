"""URL map for PANIC Server (/api/v1/health, /api/v1/version, /metrics, and auth).

T-S6-04 removes the whole Stage 1-5 server-rendered UI and its STORE-backed ``/api/v1/*``
endpoints (dashboards, catalog, lists, sites, teams, zones, rbac, audit, export, the .rdp
launcher, and static-file serving): all of it depended on the deleted ``STORE``/``state.py``.
This functionality is rebuilt against the new DRF/Mongo stack by T-S6-06 and T-S6-07. Until that
lands, ``main`` has no working interactive UI (see Documents/TASKS.md T-S6-04's "Transition" note).
"""

from __future__ import annotations

from django.urls import include, path

from panic_server import views

urlpatterns = [
    # Authentication (/login, /logout, OIDC callback) — panic_server.auth
    path("", include("panic_server.auth.urls")),
    # Health, version, Prometheus metrics (mirroring reference-app)
    path("api/v1/health", views.health_view, name="health"),
    path("api/v1/version", views.version_view, name="version"),
    path("metrics", views.metrics_view, name="metrics"),
]

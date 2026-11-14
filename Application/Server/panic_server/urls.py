"""URL map for PANIC Server (/api/v1/health, /api/v1/version, /metrics, auth, and the DRF API).

T-S6-04 removed the whole Stage 1-5 server-rendered UI and its STORE-backed ``/api/v1/*``
endpoints (dashboards, catalog, lists, sites, teams, zones, rbac, audit, export, the .rdp
launcher, and static-file serving): all of it depended on the deleted ``STORE``/``state.py``.
T-S6-06 rebuilds the first real slice against the new DRF/Mongo stack (auth session, UI reads,
the .rdp download) under ``panic_server.api``; T-S6-07 adds the rest (dashboards CRUD, ``/me``,
catalog/lists CRUD, sites/teams/zones/users/admin/settings/audit/export) to that same app.
"""

from __future__ import annotations

from django.urls import include, path

from panic_server import views
from panic_server.api.errors import not_found_view

urlpatterns = [
    # Authentication (OIDC login/callback; the old /login, /logout HTML-era routes are gone,
    # superseded by panic_server.api.urls' /api/v1/auth/* — panic_server.auth.urls) — panic_server.auth
    path("", include("panic_server.auth.urls")),
    # The DRF API (T-S6-06/07).
    path("api/v1/", include("panic_server.api.urls")),
    # Health, version, Prometheus metrics (mirroring reference-app; plain Django views, not DRF).
    path("api/v1/health", views.health_view, name="health"),
    path("api/v1/version", views.version_view, name="version"),
    path("metrics", views.metrics_view, name="metrics"),
]

#: An unmatched path answers with the same error envelope as everything else (API.md §1/§3),
#: not Django's default HTML 404 page.
handler404 = not_found_view

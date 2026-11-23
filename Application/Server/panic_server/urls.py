"""URL map for PANIC Server (/api/v1/health, /api/v1/version, /metrics, auth, and the DRF API).

Every ``/api/v1/*`` resource (auth session, UI reads, the .rdp download, dashboards, ``/me``,
catalog, lists, sites/teams/zones/users/admin/settings/audit/export) lives in ``panic_server.api``.
"""

from __future__ import annotations

from django.urls import include, path

from panic_server import views
from panic_server.api.errors import not_found_view

urlpatterns = [
    # Authentication (OIDC login/callback; local sign-in is panic_server.api.urls' /api/v1/auth/*)
    # — panic_server.auth
    path("", include("panic_server.auth.urls")),
    # The DRF API.
    path("api/v1/", include("panic_server.api.urls")),
    # Health, version, Prometheus metrics (plain Django views, not DRF).
    path("api/v1/health", views.health_view, name="health"),
    path("api/v1/version", views.version_view, name="version"),
    path("metrics", views.metrics_view, name="metrics"),
]

#: An unmatched path answers with the same error envelope as everything else (API.md §1/§3),
#: not Django's default HTML 404 page.
handler404 = not_found_view

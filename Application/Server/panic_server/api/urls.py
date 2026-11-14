"""``/api/v1/...`` DRF routes owned by T-S6-06 (auth session, UI reads, the ``.rdp`` download).

T-S6-07 adds dashboards CRUD, ``/me``, catalog/lists CRUD, sites/teams/zones/users/admin/
settings/audit/export under this same ``urlpatterns`` list.
"""

from __future__ import annotations

from django.urls import path

from panic_server.api.views import auth as auth_views
from panic_server.api.views import launch as launch_views
from panic_server.api.views import ui as ui_views
from panic_server.openapi import hooks as _openapi_hooks  # noqa: F401 - registers drf-spectacular extensions

urlpatterns = [
    path("auth/providers", auth_views.providers_view, name="auth-providers"),
    path("auth/csrf", auth_views.csrf_view, name="auth-csrf"),
    path("auth/login", auth_views.login_view, name="auth-login"),
    path("auth/logout", auth_views.logout_view, name="auth-logout"),
    path("ui/bootstrap", ui_views.bootstrap_view, name="ui-bootstrap"),
    path("ui/dashboards/<str:dashboard_id>", ui_views.dashboard_view, name="ui-dashboard"),
    path("ui/search", ui_views.search_view, name="ui-search"),
    path("launch/rdp/<str:item_id>.rdp", launch_views.rdp_download_view, name="launch-rdp"),
]

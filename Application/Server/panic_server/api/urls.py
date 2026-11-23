"""``/api/v1/...`` DRF routes: auth session, UI reads, the ``.rdp`` download, dashboards CRUD,
``/me``, catalog/lists CRUD, sites/teams/zones/users/admin/settings/audit/export.
"""

from __future__ import annotations

from django.urls import path

from panic_server.api.views import admin as admin_views
from panic_server.api.views import audit as audit_views
from panic_server.api.views import auth as auth_views
from panic_server.api.views import catalog as catalog_views
from panic_server.api.views import dashboards as dashboards_views
from panic_server.api.views import diagnostics as diagnostics_views
from panic_server.api.views import export as export_views
from panic_server.api.views import launch as launch_views
from panic_server.api.views import lists as lists_views
from panic_server.api.views import me as me_views
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
    # -------------------------------------------------------------- resources
    path("dashboards", dashboards_views.dashboards_view, name="dashboards-list"),
    path("dashboards/<str:dashboard_id>", dashboards_views.dashboard_detail_view, name="dashboard-detail"),
    path("dashboards/<str:dashboard_id>/layout", dashboards_views.dashboard_layout_view, name="dashboard-layout"),
    path("me", me_views.me_view, name="me"),
    path("me/default-dashboard", me_views.default_dashboard_view, name="me-default-dashboard"),
    path("me/menu/<str:dashboard_id>", me_views.menu_pin_view, name="me-menu"),
    path("catalog", catalog_views.catalog_view, name="catalog-list"),
    path("catalog/preview", catalog_views.catalog_preview_view, name="catalog-preview"),
    path("catalog/<str:item_id>", catalog_views.catalog_detail_view, name="catalog-detail"),
    path("lists", lists_views.lists_view, name="lists-list"),
    path("lists/<str:list_id>", lists_views.list_detail_view, name="list-detail"),
    path("sites", admin_views.sites_view, name="sites-list"),
    path("sites/<str:site_id>", admin_views.site_detail_view, name="site-detail"),
    path("teams", admin_views.teams_view, name="teams-list"),
    path("teams/<str:team_id>", admin_views.team_detail_view, name="team-detail"),
    path("teams/<str:team_id>/members", admin_views.team_members_view, name="team-members"),
    path("zones", admin_views.zones_view, name="zones-list"),
    path("zones/test-ip", admin_views.zone_test_ip_view, name="zone-test-ip"),
    path("zones/<str:zone_id>", admin_views.zone_detail_view, name="zone-detail"),
    path("users", admin_views.users_view, name="users-list"),
    path("users/<str:user_id>", admin_views.user_detail_view, name="user-detail"),
    path("admin/orphans", admin_views.orphans_view, name="orphans-list"),
    path("admin/orphans/<str:kind>/<str:item_id>/assign", admin_views.orphan_assign_view, name="orphan-assign"),
    path("admin/view-as", admin_views.view_as_view, name="admin-view-as"),
    path("admin/client-ip", diagnostics_views.client_ip_view, name="admin-client-ip"),
    path("settings", admin_views.settings_view, name="settings"),
    path("audit", audit_views.audit_view, name="audit"),
    path("export", export_views.export_view, name="export"),
]

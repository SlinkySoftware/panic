"""URL map for PANIC Server (HTML shell + /api/v1/* + /metrics)."""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path, re_path

from panic_server import views

urlpatterns = [
    # Authentication (/login, /logout, OIDC callback) — panic_server.auth
    path("", include("panic_server.auth.urls")),
    # Server-rendered UI routes (explicit, visible URLs — no hidden URLs)
    path("", views.portal_app_view, {"initial_view": "dashboard"}, name="home"),
    path("dashboard", views.portal_app_view, {"initial_view": "dashboard"}, name="dashboard_default"),
    path("dashboard/", views.portal_app_view, {"initial_view": "dashboard"}, name="dashboard_default_slash"),
    path(
        "dashboard/<str:dashboard_id>",
        views.portal_app_view,
        {"initial_view": "dashboard"},
        name="dashboard_detail",
    ),
    path(
        "dashboard/<str:dashboard_id>/",
        views.portal_app_view,
        {"initial_view": "dashboard"},
        name="dashboard_detail_slash",
    ),
    path(
        "dashboard/<str:dashboard_id>/edit",
        views.portal_app_view,
        {"initial_view": "dashboard", "initial_edit": True},
        name="dashboard_edit",
    ),
    path(
        "dashboard/<str:dashboard_id>/edit/",
        views.portal_app_view,
        {"initial_view": "dashboard", "initial_edit": True},
        name="dashboard_edit_slash",
    ),
    path("catalog", views.portal_app_view, {"initial_view": "catalog"}, name="catalog"),
    path("catalog/", views.portal_app_view, {"initial_view": "catalog"}, name="catalog_slash"),
    path("lists", views.portal_app_view, {"initial_view": "lists"}, name="lists"),
    path("lists/", views.portal_app_view, {"initial_view": "lists"}, name="lists_slash"),
    path("sites", views.portal_app_view, {"initial_view": "sites"}, name="sites"),
    path("sites/", views.portal_app_view, {"initial_view": "sites"}, name="sites_slash"),
    path("teams", views.portal_app_view, {"initial_view": "teams"}, name="teams"),
    path("teams/", views.portal_app_view, {"initial_view": "teams"}, name="teams_slash"),
    path("zones", views.portal_app_view, {"initial_view": "zones"}, name="zones"),
    path("zones/", views.portal_app_view, {"initial_view": "zones"}, name="zones_slash"),
    path("rbac", views.portal_app_view, {"initial_view": "rbac"}, name="rbac"),
    path("rbac/", views.portal_app_view, {"initial_view": "rbac"}, name="rbac_slash"),
    path("settings", views.portal_app_view, {"initial_view": "settings"}, name="settings"),
    path("settings/", views.portal_app_view, {"initial_view": "settings"}, name="settings_slash"),
    path("profile", views.portal_app_view, {"initial_view": "profile"}, name="profile"),
    path("profile/", views.portal_app_view, {"initial_view": "profile"}, name="profile_slash"),
    path("audit", views.portal_app_view, {"initial_view": "audit"}, name="audit"),
    path("audit/", views.portal_app_view, {"initial_view": "audit"}, name="audit_slash"),
    # Health, version, Prometheus metrics (mirroring reference-app)
    path("api/v1/health", views.health_view, name="health"),
    path("api/v1/version", views.version_view, name="version"),
    path("metrics", views.metrics_view, name="metrics"),
    # Ephemeral .rdp download endpoint
    path("api/v1/launch/rdp/<str:target_id>.rdp", views.rdp_download_view, name="rdp_download"),
    # Stage 1 interactive state & mutation APIs
    path("api/v1/state", views.state_api_view, name="api_state"),
    path("api/v1/simulator", views.simulator_api_view, name="api_simulator"),
    path("api/v1/profile", views.profile_api_view, name="api_profile"),
    path("api/v1/settings", views.settings_api_view, name="api_settings"),
    path("api/v1/dashboards", views.dashboards_api_view, name="api_dashboards"),
    path(
        "api/v1/dashboards/<str:dashboard_id>/layout",
        views.dashboard_layout_api_view,
        name="api_dashboard_layout",
    ),
    path("api/v1/catalog/preview-share", views.catalog_preview_share_api_view, name="api_catalog_preview"),
    path("api/v1/catalog", views.catalog_api_view, name="api_catalog"),
    path("api/v1/lists", views.lists_api_view, name="api_lists"),
    path("api/v1/sites", views.sites_api_view, name="api_sites"),
    path("api/v1/teams", views.teams_api_view, name="api_teams"),
    path("api/v1/zones", views.zones_api_view, name="api_zones"),
    path("api/v1/audit", views.audit_api_view, name="api_audit"),
    path("api/v1/export", views.export_api_view, name="api_export"),
    path("api/v1/rbac", views.rbac_api_view, name="api_rbac"),
]

if settings.PANIC_SERVE_STATIC and not settings.DEBUG:
    # Production static serving from STATIC_ROOT (collectstatic). In DEBUG, staticfiles' runserver handles it.
    urlpatterns.append(
        re_path(r"^static/(?P<path>.*)$", views.static_asset_view, name="static_asset"),
    )

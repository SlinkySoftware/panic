"""Server-rendered HTML views, REST API endpoints, RBAC enforcement, and ephemeral .rdp launcher."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from panic_common.errors import ErrorCode
from panic_common.hygiene import preview_catalog_submission
from panic_common.launchers import generate_rdp_content, sanitize_launch_param
from panic_common.models import (
    CatalogItem,
    Dashboard,
    DashboardWidget,
    DensityMode,
    EndpointList,
    PermissionFlag,
    Protocol,
    ScopeType,
    SecurityZone,
    SiteDefinition,
    TeamDefinition,
    ThemeMode,
    UnreachablePolicy,
    UserAccount,
    WidgetType,
)
from panic_common.rbac import (
    can_create_or_edit_scope,
    can_use_view_as,
    has_permission,
    is_visible_in_scope,
    validate_list_item_scopes,
)
from panic_common.zones import check_item_reachability, resolve_ip_zone, validate_cidr_list
from panic_server import __version__
from panic_server.portability import export_state
from panic_server.state import STORE


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_body(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def portal_app_view(
    request: HttpRequest,
    initial_view: str = "dashboard",
    dashboard_id: str | None = None,
    initial_edit: bool = False,
) -> HttpResponse:
    """Render the server-side HTML shell hydrated with the Stage 1 state snapshot and explicit route context."""
    snapshot = STORE.build_snapshot()
    resolved_dash_id = ""
    if initial_view == "dashboard":
        if dashboard_id:
            candidate_id = STORE.resolve_dashboard_id(dashboard_id)
            accessible_ids = {d["id"] for d in snapshot.get("accessible_dashboards", [])}
            if candidate_id in accessible_ids:
                resolved_dash_id = candidate_id
        if not resolved_dash_id:
            resolved_dash_id = str(snapshot["user"].get("effective_default_dashboard_id") or "")

    context = {
        "instance_name": getattr(settings, "PANIC_INSTANCE_NAME", "PANIC"),
        "version": __version__,
        "initial_view": initial_view,
        "initial_dashboard_id": resolved_dash_id,
        "initial_edit": initial_edit,
        "auth_session": settings.PANIC_AUTH_MODE == "session",
        "initial_state_json": json.dumps(snapshot),
        "snapshot": snapshot,
    }
    return render(request, "panic/index.html", context)


def health_view(request: HttpRequest) -> JsonResponse:
    db_ok = STORE.database_ok()
    return JsonResponse(
        {
            "status": "ok" if db_ok else "degraded",
            "component": "panic-server",
            "stage": "stage-2-relational",
            "database": {"engine": settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1], "ok": db_ok},
        },
        status=200 if db_ok else 503,
    )


def version_view(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"name": "panic-server", "version": __version__, "stage": 2})


def export_api_view(request: HttpRequest) -> JsonResponse:
    """Portable JSON export of portal state (``GLOBAL_ADMIN`` only)."""
    if not has_permission(STORE.auth_user, PermissionFlag.GLOBAL_ADMIN):
        return JsonResponse(
            {"error_code": ErrorCode.PERMISSION_DENIED, "detail": "Export requires Global Admin"}, status=403
        )
    shared_only = request.GET.get("shared_only", "").lower() in {"1", "true", "yes"}
    STORE.record_audit(
        action="system.export",
        target_type="system",
        target_id="portal",
        summary=f"Exported portal state (shared_only={shared_only})",
    )
    response = JsonResponse(export_state(STORE, shared_only=shared_only))
    response["Content-Disposition"] = 'attachment; filename="panic-export.json"'
    return response


def metrics_view(request: HttpRequest) -> HttpResponse:
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)


def rdp_download_view(request: HttpRequest, target_id: str) -> HttpResponse:
    """Dynamically generate and stream an ephemeral .rdp file (SPEC §4.2, §5.2)."""
    target = STORE.find_launch_target(target_id)
    if target is None:
        return JsonResponse(
            {"error_code": ErrorCode.NOT_FOUND, "detail": f"RDP target {target_id!r} not found"},
            status=404,
        )
    host, port, username, title = target
    override_user = request.GET.get("user", "").strip()
    if override_user:
        username = sanitize_launch_param(override_user)

    rdp_content = generate_rdp_content(
        host=host,
        port=port,
        username=username,
        title=title,
    )
    safe_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", f"{title}-{host}".lower()).strip("-") or "session"
    response = HttpResponse(rdp_content, content_type="application/x-rdp; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{safe_slug}.rdp"'
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    STORE.record_audit(
        action="launch.rdp.download",
        target_type="endpoint",
        target_id=target_id,
        summary=f"Generated ephemeral .rdp launcher for {host}:{port} (user: {username})",
        details={"host": host, "port": port, "username": username},
    )
    return response


@csrf_exempt
def state_api_view(request: HttpRequest) -> JsonResponse:
    if request.method == "POST":
        body = _json_body(request)
        if body.get("action") == "reset":
            if not settings.PANIC_DEV_SIMULATOR_ENABLED:
                return JsonResponse(
                    {"error_code": ErrorCode.PERMISSION_DENIED, "detail": "Reset is only available in simulator mode"},
                    status=403,
                )
            STORE.reset()
            STORE.record_audit(
                action="simulator.reset",
                target_type="system",
                target_id="stage1-mock",
                summary="Reset Stage 1 mock state to factory seed fixtures",
            )
    return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def simulator_api_view(request: HttpRequest) -> JsonResponse:
    """Update the Stage 1 Source IP / Zone and Active User (RBAC) Simulator."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    if not settings.PANIC_DEV_SIMULATOR_ENABLED:
        # Live mode: source IP / zone come from the request and identity from the session.
        if "active_user_id" in body:
            return JsonResponse(
                {
                    "error_code": ErrorCode.PERMISSION_DENIED,
                    "detail": "User switching is disabled outside simulator mode",
                },
                status=403,
            )
        body.pop("simulated_ip", None)
        body.pop("override_zone_id", None)
    with STORE._lock:
        if "simulated_ip" in body:
            ip_val = str(body["simulated_ip"]).strip()
            if ip_val:
                STORE.simulation.simulated_ip = ip_val

        if "override_zone_id" in body:
            oz = body["override_zone_id"]
            STORE.simulation.override_zone_id = str(oz) if oz else None

        if "active_user_id" in body:
            uid = str(body["active_user_id"]).strip()
            if any(u.id == uid for u in STORE.users):
                STORE.simulation.active_user_id = uid
                STORE.simulation.view_as_user_id = None

        if "view_as_user_id" in body:
            auth_user = STORE.auth_user
            if not can_use_view_as(auth_user):
                return JsonResponse(
                    {
                        "error_code": ErrorCode.PERMISSION_DENIED,
                        "detail": "RBAC Denied: 'View As' capability requires Admin ('Global Admin') permissions.",
                    },
                    status=403,
                )
            raw_view_as = body["view_as_user_id"]
            target_uid = str(raw_view_as).strip() if raw_view_as else ""
            if not target_uid or target_uid == auth_user.id:
                STORE.simulation.view_as_user_id = None
                STORE.record_audit(
                    action="rbac.view_as.exit",
                    target_type="user_account",
                    target_id=auth_user.id,
                    summary=f"Admin {auth_user.username} exited 'View As' mode",
                )
            else:
                target_user = next((u for u in STORE.users if u.id == target_uid), None)
                if target_user is None:
                    return JsonResponse(
                        {"error_code": ErrorCode.NOT_FOUND, "detail": "Target user for 'View As' not found"},
                        status=404,
                    )
                STORE.simulation.view_as_user_id = target_user.id
                STORE.record_audit(
                    action="rbac.view_as.start",
                    target_type="user_account",
                    target_id=target_user.id,
                    summary=f"Admin {auth_user.username} viewing portal as {target_user.username}",
                )

        if "unreachable_policy" in body:
            pol = str(body["unreachable_policy"]).upper()
            if pol in {"HIDE", "DIM"}:
                STORE.active_user.unreachable_policy = UnreachablePolicy(pol)

    return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def profile_api_view(request: HttpRequest) -> JsonResponse:
    """Update User Profile settings (SSH template, default user, default dashboard, density, theme)."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    with STORE._lock:
        user = STORE.active_user
        if "display_name" in body:
            user.display_name = sanitize_launch_param(str(body["display_name"])) or user.display_name
        if "default_remote_user" in body:
            clean_user = sanitize_launch_param(str(body["default_remote_user"]))
            if ":" in clean_user or " " in clean_user:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.CREDENTIAL_HYGIENE_VIOLATION,
                        "detail": "Default remote user cannot contain spaces or colons (passwords).",
                    },
                    status=400,
                )
            if clean_user:
                user.default_remote_user = clean_user
        if "ssh_template" in body:
            tpl = sanitize_launch_param(str(body["ssh_template"]))
            if any(flag in tpl.lower() for flag in ("-pw ", "--password", "sshpass")):
                return JsonResponse(
                    {
                        "error_code": ErrorCode.CREDENTIAL_HYGIENE_VIOLATION,
                        "detail": "SSH command template must not contain plaintext password flags.",
                    },
                    status=400,
                )
            if tpl:
                user.ssh_template = tpl
        if "default_dashboard_id" in body:
            raw_dash_id = body["default_dashboard_id"]
            clean_dash_id = STORE.resolve_dashboard_id(str(raw_dash_id).strip()) if raw_dash_id else ""
            if not clean_dash_id:
                user.default_dashboard_id = None
            else:
                target_dash = next((d for d in STORE.dashboards if d.id == clean_dash_id), None)
                if target_dash is None:
                    return JsonResponse(
                        {"error_code": ErrorCode.NOT_FOUND, "detail": "Selected default dashboard not found"},
                        status=404,
                    )
                if not is_visible_in_scope(
                    user, target_dash.scope, target_dash.team_ids, target_dash.owner_usernames
                ):
                    return JsonResponse(
                        {
                            "error_code": ErrorCode.PERMISSION_DENIED,
                            "detail": "Selected dashboard is not available in your scope.",
                        },
                        status=403,
                    )
                user.default_dashboard_id = target_dash.id
                if target_dash.id not in user.pinned_dashboard_ids:
                    user.pinned_dashboard_ids.append(target_dash.id)
        if "density" in body and str(body["density"]).upper() in {"COMFORT", "COMPACT"}:
            user.density = DensityMode(str(body["density"]).upper())
        if "theme" in body and str(body["theme"]).upper() in {"DARK", "LIGHT"}:
            user.theme = ThemeMode(str(body["theme"]).upper())
        if "unreachable_policy" in body and str(body["unreachable_policy"]).upper() in {"HIDE", "DIM"}:
            user.unreachable_policy = UnreachablePolicy(str(body["unreachable_policy"]).upper())

        STORE.record_audit(
            action="profile.update",
            target_type="user_profile",
            target_id=user.id,
            summary=(
                f"Updated preferences for {user.username} "
                f"(remote_user={user.default_remote_user}, "
                f"default_dashboard={user.default_dashboard_id or 'SYSTEM_GLOBAL'})"
            ),
            details={
                "ssh_template": user.ssh_template,
                "density": user.density.value,
                "default_dashboard_id": user.default_dashboard_id,
            },
        )

    return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def settings_api_view(request: HttpRequest) -> JsonResponse:
    """View or update App-wide System Settings (e.g., Default Global Dashboard)."""
    if request.method == "GET":
        return JsonResponse(STORE.build_snapshot())
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    with STORE._lock:
        user = STORE.active_user
        if not has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return JsonResponse(
                {
                    "error_code": ErrorCode.PERMISSION_DENIED,
                    "detail": "RBAC Denied: Modifying App-wide System Settings requires 'Global Admin' permission.",
                },
                status=403,
            )

        if "default_global_dashboard_id" in body:
            target_id = STORE.resolve_dashboard_id(str(body["default_global_dashboard_id"]).strip())
            if not target_id:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "Default Global Dashboard ID is required.",
                    },
                    status=400,
                )
            dash = next((d for d in STORE.dashboards if d.id == target_id), None)
            if dash is None:
                return JsonResponse(
                    {"error_code": ErrorCode.NOT_FOUND, "detail": "Dashboard not found"},
                    status=404,
                )
            if dash.scope != ScopeType.GLOBAL:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "The Default Global Dashboard must have GLOBAL scope.",
                    },
                    status=400,
                )
            STORE.system_settings.default_global_dashboard_id = dash.id
            STORE.system_settings.updated_by = user.username
            STORE.system_settings.updated_at = _now_iso()
            STORE.record_audit(
                action="system.settings.update",
                target_type="system_settings",
                target_id="default_global_dashboard",
                summary=f"Set App-wide Default Global Dashboard to '{dash.title}' ({dash.id})",
                details={"default_global_dashboard_id": dash.id, "title": dash.title},
            )

    return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def dashboards_api_view(request: HttpRequest) -> JsonResponse:
    """Create, update, set default, or delete a Dashboard."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    action = str(body.get("action", "create"))

    with STORE._lock:
        user = STORE.active_user
        if action == "create":
            scope_str = str(body.get("scope", "PERSONAL")).upper()
            scope = ScopeType(scope_str if scope_str in {"GLOBAL", "TEAM", "PERSONAL"} else "PERSONAL")
            allowed, reason = can_create_or_edit_scope(user, scope)
            if not allowed:
                return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)

            title = sanitize_launch_param(str(body.get("title", "New Operations Dashboard"))) or "New Dashboard"
            description = str(body.get("description", ""))
            team_ids = [str(t) for t in body.get("team_ids", []) if str(t).strip()]
            if scope == ScopeType.TEAM and not team_ids:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "Team dashboards must specify at least 1 Team.",
                    },
                    status=400,
                )
            owner_usernames = [str(u) for u in body.get("owner_usernames", []) if str(u).strip()]
            if scope == ScopeType.PERSONAL and not owner_usernames:
                owner_usernames = [user.username]
            always_display = (
                bool(body.get("always_display", False))
                if scope in {ScopeType.GLOBAL, ScopeType.TEAM}
                else False
            )

            dash_id = str(uuid.uuid4())
            default_list_id = STORE.lists[0].id if STORE.lists else None
            new_dash = Dashboard(
                id=dash_id,
                title=title,
                description=description,
                scope=scope,
                team_ids=team_ids if scope == ScopeType.TEAM else [],
                owner_usernames=owner_usernames if scope == ScopeType.PERSONAL else [],
                always_display=always_display,
                sort_order=len(STORE.dashboards) + 1,
                created_by=user.username,
                widgets=(
                    [
                        DashboardWidget(
                            id=f"w-{uuid.uuid4().hex[:6]}",
                            dashboard_id=dash_id,
                            widget_type=WidgetType.LIST,
                            title="Routers",
                            grid_x=1,
                            grid_y=1,
                            grid_w=12,
                            grid_h=1,
                            list_id=default_list_id,
                        )
                    ]
                    if default_list_id
                    else []
                ),
            )
            STORE.dashboards.append(new_dash)
            if dash_id not in user.pinned_dashboard_ids:
                user.pinned_dashboard_ids.append(dash_id)
            if body.get("set_as_user_default"):
                user.default_dashboard_id = dash_id
            if (
                body.get("set_as_global_default")
                and scope == ScopeType.GLOBAL
                and has_permission(user, PermissionFlag.GLOBAL_ADMIN)
            ):
                STORE.system_settings.default_global_dashboard_id = dash_id
                STORE.system_settings.updated_by = user.username
                STORE.system_settings.updated_at = _now_iso()

            STORE.record_audit(
                "dashboard.create",
                "dashboard",
                dash_id,
                f"Created {scope.value} dashboard '{title}' (always_display={always_display})",
                {"scope": scope.value, "team_ids": team_ids, "always_display": always_display},
            )
            return JsonResponse({"created_dashboard_id": dash_id, "state": STORE.build_snapshot()})

        if action == "set_user_default":
            raw_dash_id = body.get("dashboard_id")
            dash_id = STORE.resolve_dashboard_id(str(raw_dash_id).strip()) if raw_dash_id else ""
            if not dash_id:
                user.default_dashboard_id = None
                STORE.record_audit(
                    "dashboard.default.user_clear",
                    "dashboard",
                    "SYSTEM_GLOBAL",
                    f"Cleared personal default dashboard for {user.username} (using Default Global Dashboard)",
                )
                return JsonResponse({"default_dashboard_id": None, "state": STORE.build_snapshot()})

            dash = next((d for d in STORE.dashboards if d.id == dash_id), None)
            if dash is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Dashboard not found"}, status=404)
            if not is_visible_in_scope(user, dash.scope, dash.team_ids, dash.owner_usernames):
                return JsonResponse(
                    {
                        "error_code": ErrorCode.PERMISSION_DENIED,
                        "detail": "You do not have access to set this dashboard as your default.",
                    },
                    status=403,
                )
            user.default_dashboard_id = dash.id
            if dash.id not in user.pinned_dashboard_ids:
                user.pinned_dashboard_ids.append(dash.id)
            STORE.record_audit(
                "dashboard.default.user_set",
                "dashboard",
                dash.id,
                f"Set personal default dashboard for {user.username} to '{dash.title}' ({dash.id})",
            )
            return JsonResponse({"default_dashboard_id": dash.id, "state": STORE.build_snapshot()})

        if action == "set_global_default":
            if not has_permission(user, PermissionFlag.GLOBAL_ADMIN):
                return JsonResponse(
                    {
                        "error_code": ErrorCode.PERMISSION_DENIED,
                        "detail": (
                            "RBAC Denied: Setting the App-wide Default Global Dashboard "
                            "requires 'Global Admin' permission."
                        ),
                    },
                    status=403,
                )
            dash_id = STORE.resolve_dashboard_id(str(body.get("dashboard_id", "")).strip())
            dash = next((d for d in STORE.dashboards if d.id == dash_id), None)
            if dash is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Dashboard not found"}, status=404)
            if dash.scope != ScopeType.GLOBAL:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "Only a GLOBAL scope dashboard can be set as the App-wide Default Global Dashboard.",
                    },
                    status=400,
                )
            STORE.system_settings.default_global_dashboard_id = dash.id
            STORE.system_settings.updated_by = user.username
            STORE.system_settings.updated_at = _now_iso()
            STORE.record_audit(
                "dashboard.default.global_set",
                "dashboard",
                dash.id,
                f"Set App-wide Default Global Dashboard to '{dash.title}' ({dash.id})",
            )
            return JsonResponse({"default_global_dashboard_id": dash.id, "state": STORE.build_snapshot()})

        if action == "update_properties":
            dash_id = STORE.resolve_dashboard_id(str(body.get("dashboard_id", "")).strip())
            dash = next((d for d in STORE.dashboards if d.id == dash_id), None)
            if dash is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Dashboard not found"}, status=404)

            allowed_old, reason_old = can_create_or_edit_scope(user, dash.scope)
            if not allowed_old:
                return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason_old}, status=403)

            scope_str = str(body.get("scope", dash.scope.value)).upper()
            new_scope = ScopeType(scope_str if scope_str in {"GLOBAL", "TEAM", "PERSONAL"} else dash.scope.value)
            allowed_new, reason_new = can_create_or_edit_scope(user, new_scope)
            if not allowed_new:
                return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason_new}, status=403)

            global_def_id = STORE.resolve_dashboard_id(STORE.system_settings.default_global_dashboard_id)
            if dash.id == global_def_id and new_scope != ScopeType.GLOBAL:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": (
                            "The Default Global Dashboard must remain in GLOBAL scope. "
                            "Select a different Default Global Dashboard first."
                        ),
                    },
                    status=400,
                )

            team_ids = [str(t) for t in body.get("team_ids", dash.team_ids) if str(t).strip()]
            if new_scope == ScopeType.TEAM and not team_ids:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "Team dashboards must specify at least 1 Team.",
                    },
                    status=400,
                )

            owner_usernames = [str(u) for u in body.get("owner_usernames", dash.owner_usernames) if str(u).strip()]
            if new_scope == ScopeType.PERSONAL and not owner_usernames:
                owner_usernames = [user.username]

            if "title" in body and str(body["title"]).strip():
                dash.title = sanitize_launch_param(str(body["title"])) or dash.title
            if "description" in body:
                dash.description = str(body["description"]).strip()
            dash.scope = new_scope
            dash.team_ids = team_ids if new_scope == ScopeType.TEAM else []
            dash.owner_usernames = owner_usernames if new_scope == ScopeType.PERSONAL else []
            if new_scope in {ScopeType.GLOBAL, ScopeType.TEAM}:
                if "always_display" in body:
                    dash.always_display = bool(body["always_display"])
            else:
                dash.always_display = False

            if "set_as_user_default" in body:
                if bool(body["set_as_user_default"]):
                    user.default_dashboard_id = dash.id
                elif user.default_dashboard_id == dash.id:
                    user.default_dashboard_id = None

            if (
                "set_as_global_default" in body
                and bool(body["set_as_global_default"])
                and new_scope == ScopeType.GLOBAL
                and has_permission(user, PermissionFlag.GLOBAL_ADMIN)
            ):
                STORE.system_settings.default_global_dashboard_id = dash.id
                STORE.system_settings.updated_by = user.username
                STORE.system_settings.updated_at = _now_iso()

            STORE.record_audit(
                "dashboard.properties.update",
                "dashboard",
                dash.id,
                f"Updated dashboard properties for '{dash.title}' "
                f"(scope={dash.scope.value}, always_display={dash.always_display})",
                {
                    "scope": dash.scope.value,
                    "team_ids": dash.team_ids,
                    "always_display": dash.always_display,
                },
            )
            return JsonResponse({"updated_dashboard_id": dash.id, "state": STORE.build_snapshot()})

        if action == "add_existing":
            dash_id = STORE.resolve_dashboard_id(str(body.get("dashboard_id", "")).strip())
            dash = next((d for d in STORE.dashboards if d.id == dash_id), None)
            if dash is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Dashboard not found"}, status=404)
            if dash.scope not in {ScopeType.GLOBAL, ScopeType.TEAM}:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "Only Global or Team dashboards can be added via 'Add Existing'.",
                    },
                    status=400,
                )
            if not is_visible_in_scope(user, dash.scope, dash.team_ids, dash.owner_usernames):
                return JsonResponse(
                    {
                        "error_code": ErrorCode.PERMISSION_DENIED,
                        "detail": "You do not have team/scope access to this dashboard.",
                    },
                    status=403,
                )
            if dash.id not in user.pinned_dashboard_ids:
                user.pinned_dashboard_ids.append(dash.id)
            STORE.record_audit(
                "dashboard.menu.add",
                "dashboard",
                dash.id,
                f"Added existing {dash.scope.value} dashboard '{dash.title}' to menu for {user.username}",
            )
            return JsonResponse({"added_dashboard_id": dash.id, "state": STORE.build_snapshot()})

        if action == "remove_from_menu":
            dash_id = STORE.resolve_dashboard_id(str(body.get("dashboard_id", "")).strip())
            dash = next((d for d in STORE.dashboards if d.id == dash_id), None)
            if dash and dash.always_display and dash.scope in {ScopeType.GLOBAL, ScopeType.TEAM}:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "This dashboard has 'Always Display' enabled and cannot be removed from the menu.",
                    },
                    status=400,
                )
            global_def_id = STORE.resolve_dashboard_id(STORE.system_settings.default_global_dashboard_id)
            if dash_id == global_def_id:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "This is the App-wide Default Global Dashboard and cannot be removed from the menu.",
                    },
                    status=400,
                )
            user.pinned_dashboard_ids = [STORE.resolve_dashboard_id(did) for did in user.pinned_dashboard_ids]
            if dash_id in user.pinned_dashboard_ids:
                if len(user.pinned_dashboard_ids) <= 1:
                    return JsonResponse(
                        {
                            "error_code": ErrorCode.VALIDATION_ERROR,
                            "detail": "At least one dashboard must remain in your navigation menu.",
                        },
                        status=400,
                    )
                user.pinned_dashboard_ids = [did for did in user.pinned_dashboard_ids if did != dash_id]
                if user.default_dashboard_id and STORE.resolve_dashboard_id(user.default_dashboard_id) == dash_id:
                    user.default_dashboard_id = None
                STORE.record_audit(
                    "dashboard.menu.remove",
                    "dashboard",
                    dash_id,
                    f"Removed dashboard {dash_id} from navigation menu for {user.username}",
                )
            return JsonResponse({"state": STORE.build_snapshot()})

        if action == "delete":
            dash_id = STORE.resolve_dashboard_id(
                str(body.get("dashboard_id") or body.get("id") or "").strip()
            )
            dash = next((d for d in STORE.dashboards if d.id == dash_id), None)
            if dash is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Dashboard not found"}, status=404)
            allowed, reason = can_create_or_edit_scope(user, dash.scope)
            if not allowed:
                return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)
            global_def_id = STORE.resolve_dashboard_id(STORE.system_settings.default_global_dashboard_id)
            if dash.id == global_def_id:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": (
                            "Cannot delete the current Default Global Dashboard. "
                            "Select a different Default Global Dashboard in System Settings first."
                        ),
                    },
                    status=400,
                )
            if len(STORE.dashboards) <= 1:
                return JsonResponse(
                    {"error_code": ErrorCode.VALIDATION_ERROR, "detail": "Cannot delete the last dashboard"},
                    status=400,
                )
            STORE.dashboards = [d for d in STORE.dashboards if d.id != dash_id]
            for u in STORE.users:
                u.pinned_dashboard_ids = [
                    STORE.resolve_dashboard_id(did)
                    for did in u.pinned_dashboard_ids
                    if STORE.resolve_dashboard_id(did) != dash_id
                ]
                if u.default_dashboard_id and STORE.resolve_dashboard_id(u.default_dashboard_id) == dash_id:
                    u.default_dashboard_id = None
            STORE.record_audit("dashboard.delete", "dashboard", dash_id, f"Deleted dashboard '{dash.title}'")
            return JsonResponse({"state": STORE.build_snapshot()})

    return JsonResponse({"state": STORE.build_snapshot()})


@csrf_exempt
def dashboard_layout_api_view(request: HttpRequest, dashboard_id: str) -> JsonResponse:
    """Persist Zabbix-style grid layout (only HOST and LIST widgets, with x, y, w, h) on Save."""
    if request.method not in {"PUT", "POST"}:
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "PUT/POST required"}, status=405)

    body = _json_body(request)
    with STORE._lock:
        user = STORE.active_user
        resolved_dash_id = STORE.resolve_dashboard_id(dashboard_id)
        dash = next((d for d in STORE.dashboards if d.id == resolved_dash_id), None)
        if dash is None:
            return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Dashboard not found"}, status=404)

        allowed, reason = can_create_or_edit_scope(user, dash.scope)
        if not allowed:
            return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)

        if "title" in body and str(body["title"]).strip():
            dash.title = sanitize_launch_param(str(body["title"]))
        if "description" in body:
            dash.description = str(body["description"]).strip()

        raw_widgets = body.get("widgets")
        if isinstance(raw_widgets, list):
            updated_widgets: list[DashboardWidget] = []
            for rw in raw_widgets:
                if not isinstance(rw, dict):
                    continue
                wid = str(rw.get("id") or f"w-{uuid.uuid4().hex[:6]}")
                wtype_str = str(rw.get("widget_type", "HOST")).upper()
                wtype = WidgetType.LIST if wtype_str == "LIST" else WidgetType.HOST
                gx = max(1, min(12, int(rw.get("grid_x", 1))))
                gy = max(1, int(rw.get("grid_y", 1)))
                gw = max(3, min(12, int(rw.get("grid_w", 4 if wtype == WidgetType.HOST else 12))))
                if gx + gw - 1 > 12:
                    gx = max(1, 13 - gw)
                gh = max(1, min(6, int(rw.get("grid_h", 1))))

                cat_id = rw.get("catalog_item_id") or None
                list_id = rw.get("list_id") or None
                title = sanitize_launch_param(str(rw.get("title", "")))

                updated_widgets.append(
                    DashboardWidget(
                        id=wid,
                        dashboard_id=dash.id,
                        widget_type=wtype,
                        title=title,
                        grid_x=gx,
                        grid_y=gy,
                        grid_w=gw,
                        grid_h=gh,
                        catalog_item_id=str(cat_id) if cat_id else None,
                        list_id=str(list_id) if list_id else None,
                    )
                )
            dash.widgets = updated_widgets
            STORE.record_audit(
                action="dashboard.layout.save",
                target_type="dashboard",
                target_id=dash.id,
                summary=f"Saved grid layout for '{dash.title}' ({len(updated_widgets)} widgets)",
            )

    return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def catalog_preview_share_api_view(request: HttpRequest) -> JsonResponse:
    """Run live Normalization & Deduplication + Credential Hygiene check."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)
    body = _json_body(request)
    preview = STORE.preview_share(body)
    return JsonResponse(preview)


@csrf_exempt
def catalog_api_view(request: HttpRequest) -> JsonResponse:
    """Create, update, or delete Catalog items with RBAC, Scope (Global/Team/Personal), Site, and Zone restrictions."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    action = str(body.get("action", "create"))

    with STORE._lock:
        user = STORE.active_user
        if action == "delete":
            item_id = str(body.get("id", ""))
            item = next((c for c in STORE.catalog if c.id == item_id), None)
            if item is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Item not found"}, status=404)
            allowed, reason = can_create_or_edit_scope(user, item.scope)
            if not allowed:
                return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)
            STORE.catalog = [c for c in STORE.catalog if c.id != item_id]
            for lst in STORE.lists:
                lst.item_ids = [iid for iid in lst.item_ids if iid != item_id]
            STORE.record_audit("catalog.delete", "catalog_item", item_id, f"Deleted catalog item '{item.title}'")
            return JsonResponse({"state": STORE.build_snapshot()})

        scope_str = str(body.get("scope", "GLOBAL")).upper()
        scope = ScopeType(scope_str if scope_str in {"GLOBAL", "TEAM", "PERSONAL"} else "GLOBAL")
        allowed, reason = can_create_or_edit_scope(user, scope)
        if not allowed:
            return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)

        protocol = Protocol(str(body.get("protocol", "SSH")).upper())
        host = sanitize_launch_param(str(body.get("host", "")))
        raw_port = body.get("port")
        if protocol in {Protocol.LOCAL_APP, Protocol.WEB}:
            port = None
        else:
            port = int(raw_port) if raw_port not in (None, "") else (3389 if protocol == Protocol.RDP else None)
        site = sanitize_launch_param(str(body.get("site", "2SYA"))).upper() or "2SYA"
        path_or_args = sanitize_launch_param(str(body.get("path_or_args", "")))
        account_override = sanitize_launch_param(str(body.get("account_override", "")))
        custom_uri = sanitize_launch_param(str(body.get("custom_uri", "")))

        edit_id = str(body.get("id", "")).strip()
        other_catalog = [c for c in STORE.catalog if c.id != edit_id]

        preview = preview_catalog_submission(
            protocol=protocol,
            host=host,
            port=port,
            path_or_args=path_or_args,
            account_override=account_override,
            custom_uri=custom_uri,
            existing_catalog=other_catalog,
        )
        if not preview.hygiene_passed:
            return JsonResponse(
                {
                    "error_code": ErrorCode.CREDENTIAL_HYGIENE_VIOLATION,
                    "detail": preview.hygiene_errors[0],
                    "hygiene_errors": preview.hygiene_errors,
                },
                status=400,
            )
        if preview.duplicate_found and not body.get("force_allow_duplicate"):
            return JsonResponse(
                {
                    "error_code": ErrorCode.DUPLICATE_CATALOG_ITEM,
                    "detail": f"Normalized target {preview.normalized_key} already exists in the Catalog.",
                    "existing_item": preview.existing_item.model_dump() if preview.existing_item else None,
                    "normalized_key": preview.normalized_key,
                },
                status=409,
            )

        team_ids = [str(t) for t in body.get("team_ids", []) if str(t).strip()]
        if scope == ScopeType.TEAM and not team_ids:
            return JsonResponse(
                {
                    "error_code": ErrorCode.VALIDATION_ERROR,
                    "detail": "Team-scoped items must select at least 1 Team.",
                },
                status=400,
            )

        owner_usernames = [str(u) for u in body.get("owner_usernames", []) if str(u).strip()]
        if scope == ScopeType.PERSONAL and not owner_usernames:
            owner_usernames = [user.username]

        zone_ids = [str(z) for z in body.get("zone_ids", []) if str(z).strip()]
        title = sanitize_launch_param(str(body.get("title", preview.resolved_host))) or preview.resolved_host
        description = str(body.get("description", ""))
        stored_host = host if protocol in {Protocol.WEB, Protocol.LOCAL_APP} else preview.resolved_host
        stored_port = None if protocol == Protocol.LOCAL_APP else preview.resolved_port

        if edit_id:
            existing = next((c for c in STORE.catalog if c.id == edit_id), None)
            if existing is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Item not found"}, status=404)
            existing.title = title
            existing.description = description
            existing.protocol = protocol
            existing.host = stored_host
            existing.port = stored_port
            existing.site = site
            existing.path_or_args = path_or_args
            existing.custom_uri = custom_uri
            existing.account_override = account_override
            existing.normalized_key = preview.normalized_key
            existing.scope = scope
            existing.team_ids = team_ids if scope == ScopeType.TEAM else []
            existing.owner_usernames = owner_usernames if scope == ScopeType.PERSONAL else []
            existing.zone_ids = zone_ids
            STORE.record_audit("catalog.update", "catalog_item", edit_id, f"Updated '{title}' ({scope.value})")
            return JsonResponse({"item_id": edit_id, "state": STORE.build_snapshot()})

        new_id = f"cat-{uuid.uuid4().hex[:6]}"
        new_item = CatalogItem(
            id=new_id,
            title=title,
            description=description,
            protocol=protocol,
            host=stored_host,
            port=stored_port,
            site=site,
            path_or_args=path_or_args,
            custom_uri=custom_uri,
            account_override=account_override,
            tags=[str(t).strip() for t in body.get("tags", []) if str(t).strip()],
            normalized_key=preview.normalized_key,
            scope=scope,
            team_ids=team_ids if scope == ScopeType.TEAM else [],
            owner_usernames=owner_usernames if scope == ScopeType.PERSONAL else [],
            zone_ids=zone_ids,
            created_by=user.username,
            created_at=_now_iso(),
        )
        STORE.catalog.insert(0, new_item)
        STORE.record_audit(
            "catalog.create",
            "catalog_item",
            new_id,
            f"Added {scope.value} item '{title}' ({preview.normalized_key}, site={site})",
            {"normalized_key": preview.normalized_key, "scope": scope.value, "site": site},
        )
        return JsonResponse({"created_item_id": new_id, "state": STORE.build_snapshot()})


@csrf_exempt
def lists_api_view(request: HttpRequest) -> JsonResponse:
    """CRUD for Endpoint Lists with Scope (Global, Team, Personal) and strict same-scope item validation."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    action = str(body.get("action", "save"))

    with STORE._lock:
        user = STORE.active_user
        if action == "delete":
            list_id = str(body.get("id", ""))
            lst = next((item for item in STORE.lists if item.id == list_id), None)
            if lst is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "List not found"}, status=404)
            allowed, reason = can_create_or_edit_scope(user, lst.scope)
            if not allowed:
                return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)
            STORE.lists = [item for item in STORE.lists if item.id != list_id]
            STORE.record_audit("list.delete", "endpoint_list", list_id, f"Deleted list '{lst.title}'")
            return JsonResponse(STORE.build_snapshot())

        if action == "reorder":
            list_id = str(body.get("id", ""))
            lst = next((item for item in STORE.lists if item.id == list_id), None)
            if lst is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "List not found"}, status=404)
            allowed, reason = can_create_or_edit_scope(user, lst.scope)
            if not allowed:
                return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)
            item_ids = [str(iid) for iid in body.get("item_ids", []) if str(iid).strip()]
            valid_scopes, scope_errors = validate_list_item_scopes(lst.scope, item_ids, STORE.catalog)
            if not valid_scopes:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.SCOPE_MISMATCH,
                        "detail": scope_errors[0],
                        "errors": scope_errors,
                    },
                    status=400,
                )
            lst.item_ids = item_ids
            STORE.record_audit(
                "list.reorder",
                "endpoint_list",
                list_id,
                f"Reordered items in {lst.scope.value} list '{lst.title}' ({len(item_ids)} items)",
                {"item_ids": item_ids},
            )
            return JsonResponse(STORE.build_snapshot())

        scope_str = str(body.get("scope", "GLOBAL")).upper()
        scope = ScopeType(scope_str if scope_str in {"GLOBAL", "TEAM", "PERSONAL"} else "GLOBAL")
        allowed, reason = can_create_or_edit_scope(user, scope)
        if not allowed:
            return JsonResponse({"error_code": ErrorCode.PERMISSION_DENIED, "detail": reason}, status=403)

        item_ids = [str(iid) for iid in body.get("item_ids", []) if str(iid).strip()]
        valid_scopes, scope_errors = validate_list_item_scopes(scope, item_ids, STORE.catalog)
        if not valid_scopes:
            return JsonResponse(
                {
                    "error_code": ErrorCode.SCOPE_MISMATCH,
                    "detail": scope_errors[0],
                    "errors": scope_errors,
                },
                status=400,
            )

        team_ids = [str(t) for t in body.get("team_ids", []) if str(t).strip()]
        if scope == ScopeType.TEAM and not team_ids:
            return JsonResponse(
                {"error_code": ErrorCode.VALIDATION_ERROR, "detail": "Team lists must specify at least 1 Team."},
                status=400,
            )

        owner_usernames = [str(u) for u in body.get("owner_usernames", []) if str(u).strip()]
        if scope == ScopeType.PERSONAL and not owner_usernames:
            owner_usernames = [user.username]

        list_id = str(body.get("id") or f"list-{uuid.uuid4().hex[:6]}")
        title = sanitize_launch_param(str(body.get("title", "Unnamed List"))) or "Unnamed List"
        description = str(body.get("description", ""))

        existing = next((item for item in STORE.lists if item.id == list_id), None)
        if existing:
            existing.title = title
            existing.description = description
            existing.scope = scope
            existing.team_ids = team_ids if scope == ScopeType.TEAM else []
            existing.owner_usernames = owner_usernames if scope == ScopeType.PERSONAL else []
            existing.item_ids = item_ids
            STORE.record_audit(
                "list.update",
                "endpoint_list",
                list_id,
                f"Updated {scope.value} list '{title}' ({len(item_ids)} items)",
            )
        else:
            STORE.lists.append(
                EndpointList(
                    id=list_id,
                    title=title,
                    description=description,
                    scope=scope,
                    team_ids=team_ids if scope == ScopeType.TEAM else [],
                    owner_usernames=owner_usernames if scope == ScopeType.PERSONAL else [],
                    item_ids=item_ids,
                    created_by=user.username,
                    created_at=_now_iso(),
                )
            )
            STORE.record_audit(
                "list.create",
                "endpoint_list",
                list_id,
                f"Created {scope.value} list '{title}' ({len(item_ids)} items)",
            )
        return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def sites_api_view(request: HttpRequest) -> JsonResponse:
    """CRUD for pre-defined Sites (requires Global Admin for mutations)."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    action = str(body.get("action", "save"))

    with STORE._lock:
        user = STORE.active_user
        if not has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return JsonResponse(
                {
                    "error_code": ErrorCode.PERMISSION_DENIED,
                    "detail": "RBAC Denied: Managing Sites requires 'Global Admin' permission.",
                },
                status=403,
            )

        if action == "delete":
            site_id = str(body.get("id", ""))
            existing = next((s for s in STORE.sites if s.id == site_id), None)
            if existing is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "Site not found"}, status=404)
            if len(STORE.sites) <= 1:
                return JsonResponse(
                    {
                        "error_code": ErrorCode.VALIDATION_ERROR,
                        "detail": "At least one pre-defined site must remain.",
                    },
                    status=400,
                )
            STORE.sites = [s for s in STORE.sites if s.id != site_id]
            STORE.record_audit("site.delete", "site", site_id, f"Deleted pre-defined site '{existing.code}'")
            return JsonResponse(STORE.build_snapshot())

        site_id = str(body.get("id") or f"site-{uuid.uuid4().hex[:6]}")
        code = sanitize_launch_param(str(body.get("code", "")).strip()).upper()
        name = sanitize_launch_param(str(body.get("name", "")).strip())
        description = str(body.get("description", "")).strip()
        if not code:
            return JsonResponse(
                {"error_code": ErrorCode.VALIDATION_ERROR, "detail": "Site code is required (e.g. 2SYA)."},
                status=400,
            )
        if not name:
            name = code

        dup = next((s for s in STORE.sites if s.code.upper() == code and s.id != site_id), None)
        if dup is not None:
            return JsonResponse(
                {
                    "error_code": ErrorCode.VALIDATION_ERROR,
                    "detail": f"Site code '{code}' already exists ({dup.name}).",
                },
                status=400,
            )

        existing = next((s for s in STORE.sites if s.id == site_id), None)
        if existing:
            old_code = existing.code
            existing.code = code
            existing.name = name
            existing.description = description
            if old_code != code:
                for cat in STORE.catalog:
                    if cat.site.upper() == old_code.upper():
                        cat.site = code
            STORE.record_audit("site.update", "site", site_id, f"Updated site '{code}' ({name})")
        else:
            STORE.sites.append(
                SiteDefinition(
                    id=site_id,
                    code=code,
                    name=name,
                    description=description,
                    created_at=_now_iso(),
                )
            )
            STORE.record_audit("site.create", "site", site_id, f"Created site '{code}' ({name})")

        return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def teams_api_view(request: HttpRequest) -> JsonResponse:
    """CRUD for Teams (requires Global Admin for mutations)."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    action = str(body.get("action", "save"))

    with STORE._lock:
        user = STORE.active_user
        if not has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return JsonResponse(
                {
                    "error_code": ErrorCode.PERMISSION_DENIED,
                    "detail": "RBAC Denied: Managing Teams requires 'Global Admin' permission.",
                },
                status=403,
            )

        if action == "delete":
            team_id = str(body.get("id", ""))
            STORE.teams = [t for t in STORE.teams if t.id != team_id]
            STORE.record_audit("team.delete", "team", team_id, f"Deleted team {team_id}")
            return JsonResponse(STORE.build_snapshot())

        team_id = str(body.get("id") or f"team-{uuid.uuid4().hex[:6]}")
        name = sanitize_launch_param(str(body.get("name", "Engineering Team"))) or "Engineering Team"
        code = sanitize_launch_param(str(body.get("code", name[:6].upper()))).upper()
        description = str(body.get("description", ""))
        raw_members = body.get("members", [])
        if isinstance(raw_members, str):
            raw_members = [m.strip() for m in raw_members.split(",") if m.strip()]
        members = [str(m) for m in raw_members if str(m).strip()]

        existing = next((t for t in STORE.teams if t.id == team_id), None)
        if existing:
            existing.name = name
            existing.code = code
            existing.description = description
            existing.members = members
            STORE.record_audit("team.update", "team", team_id, f"Updated team '{name}' ({code})")
        else:
            STORE.teams.append(
                TeamDefinition(
                    id=team_id,
                    name=name,
                    code=code,
                    description=description,
                    members=members,
                    created_at=_now_iso(),
                )
            )
            STORE.record_audit("team.create", "team", team_id, f"Created team '{name}' ({code})")

        return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def zones_api_view(request: HttpRequest) -> JsonResponse:
    """CRUD for Security Zones & linked IP CIDRs, plus interactive IP diagnostic."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    action = str(body.get("action", ""))

    with STORE._lock:
        if action == "test_ip":
            test_ip = str(body.get("ip", "")).strip()
            res = resolve_ip_zone(test_ip, STORE.zones)
            reachable_items: list[dict[str, str]] = []
            blocked_items: list[dict[str, str]] = []
            if res.valid_ip:
                for cat in STORE.catalog:
                    r = check_item_reachability(cat, res.winning_zone)
                    entry = {"id": cat.id, "title": cat.title, "protocol": cat.protocol.value, "reason": r.reason}
                    if r.reachable:
                        reachable_items.append(entry)
                    else:
                        blocked_items.append(entry)
            return JsonResponse(
                {
                    "resolution": res.model_dump(),
                    "reachable_count": len(reachable_items),
                    "blocked_count": len(blocked_items),
                    "reachable_items": reachable_items,
                    "blocked_items": blocked_items,
                }
            )

        user = STORE.active_user
        if not has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return JsonResponse(
                {
                    "error_code": ErrorCode.PERMISSION_DENIED,
                    "detail": "RBAC Denied: Modifying Security Zones requires 'Global Admin' permission.",
                },
                status=403,
            )

        if action == "save_zone":
            zone_id = str(body.get("id") or f"zone-{uuid.uuid4().hex[:6]}")
            name = sanitize_launch_param(str(body.get("name", "Unnamed Zone")))
            description = str(body.get("description", ""))
            priority = int(body.get("priority", 100))
            raw_cidrs = body.get("cidrs", [])
            if isinstance(raw_cidrs, str):
                raw_cidrs = [c.strip() for c in raw_cidrs.split(",") if c.strip()]
            try:
                cidrs = validate_cidr_list([str(c) for c in raw_cidrs])
            except ValueError as e:
                return JsonResponse({"error_code": ErrorCode.INVALID_CIDR, "detail": str(e)}, status=400)

            existing = next((z for z in STORE.zones if z.id == zone_id), None)
            if existing:
                existing.name = name
                existing.description = description
                existing.priority = priority
                existing.cidrs = cidrs
                STORE.record_audit("zone.update", "security_zone", zone_id, f"Updated zone '{name}' ({cidrs})")
            else:
                STORE.zones.append(
                    SecurityZone(
                        id=zone_id,
                        name=name,
                        description=description,
                        priority=priority,
                        cidrs=cidrs,
                        created_at=_now_iso(),
                    )
                )
                STORE.record_audit("zone.create", "security_zone", zone_id, f"Created zone '{name}' ({cidrs})")
            return JsonResponse(STORE.build_snapshot())

        if action == "delete_zone":
            zone_id = str(body.get("id", ""))
            STORE.zones = [z for z in STORE.zones if z.id != zone_id]
            STORE.record_audit("zone.delete", "security_zone", zone_id, f"Deleted security zone {zone_id}")
            return JsonResponse(STORE.build_snapshot())

    return JsonResponse(STORE.build_snapshot())


@csrf_exempt
def rbac_api_view(request: HttpRequest) -> JsonResponse:
    """Manage in-app RBAC permissions (Global Admin, Can Add to Global Scope Items, Can Add Team Scope Items)."""
    if request.method != "POST":
        return JsonResponse({"error_code": ErrorCode.VALIDATION_ERROR, "detail": "POST required"}, status=405)

    body = _json_body(request)
    action = str(body.get("action", "update_user"))

    with STORE._lock:
        if action == "update_user":
            target_uid = str(body.get("user_id", ""))
            target = next((u for u in STORE.users if u.id == target_uid), None)
            if target is None:
                return JsonResponse({"error_code": ErrorCode.NOT_FOUND, "detail": "User not found"}, status=404)

            if "permissions" in body and isinstance(body["permissions"], list):
                valid_flags = {"GLOBAL_ADMIN", "CAN_ADD_GLOBAL", "CAN_ADD_TEAM"}
                target.permissions = [
                    PermissionFlag(str(p).upper())
                    for p in body["permissions"]
                    if str(p).upper() in valid_flags
                ]
            if "team_ids" in body and isinstance(body["team_ids"], list):
                target.team_ids = [str(t) for t in body["team_ids"] if str(t).strip()]

            STORE.record_audit(
                "rbac.user.update",
                "user_account",
                target.id,
                f"Updated RBAC permissions for {target.username}: {[p.value for p in target.permissions]}",
                {"permissions": [p.value for p in target.permissions], "team_ids": target.team_ids},
            )
            return JsonResponse(STORE.build_snapshot())

        if action == "create_user":
            username = sanitize_launch_param(str(body.get("username", "operator"))).lower()
            display_name = sanitize_launch_param(str(body.get("display_name", username)))
            valid_flags = {"GLOBAL_ADMIN", "CAN_ADD_GLOBAL", "CAN_ADD_TEAM"}
            perms = [
                PermissionFlag(str(p).upper())
                for p in body.get("permissions", [])
                if str(p).upper() in valid_flags
            ]
            team_ids = [str(t) for t in body.get("team_ids", []) if str(t).strip()]
            new_uid = f"usr-{uuid.uuid4().hex[:6]}"
            STORE.users.append(
                UserAccount(
                    id=new_uid,
                    username=username,
                    display_name=display_name,
                    default_remote_user=username,
                    permissions=perms,
                    team_ids=team_ids,
                    pinned_dashboard_ids=[STORE.system_settings.default_global_dashboard_id],
                )
            )
            STORE.record_audit("rbac.user.create", "user_account", new_uid, f"Created user '{username}' in RBAC")
            return JsonResponse(STORE.build_snapshot())

    return JsonResponse(STORE.build_snapshot())

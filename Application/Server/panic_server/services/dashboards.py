"""``/api/v1/dashboards`` composition and writes (API.md §4.3). The *editable* resource shapes
here (summaries, the create/patch/layout bodies) are deliberately separate from
``panic_server.services.dashboards_read`` (T-S6-06's read-only, item-resolving ``/ui/dashboards/{id}``) --
this module never resolves widget targets into ``ItemView``s, only validates that they exist and
are visible.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from panic_common.errors import ErrorCode
from panic_common.models import DASHBOARD_ICON_RE, Dashboard, PermissionFlag, ScopeType, UserAccount, WidgetType
from panic_common.rbac import has_permission
from panic_common.search_keys import search_keys as compute_search_keys
from panic_common.visibility import Decision, can_create, can_edit, matches, visibility_spec
from panic_server.api.errors import ApiError
from panic_server.store.errors import NotFound
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import users as users_repo

MAX_WIDGETS = 100
_ALLOWED_SCOPES = {"q", "scope"}


def can_delete(user: UserAccount, resource: Any) -> Decision:
    """Catalog/list sibling of ``services.catalog.can_delete`` -- see its docstring."""
    if resource.orphaned:
        if has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.ORPHANED_RESOURCE,
            reason="Orphaned resources may only be deleted by a Global Admin, or assigned to a user.",
        )
    return can_edit(user, resource)


def _tokens(q: str) -> list[str]:
    return [tok[:64] for tok in q.split()[:8] if tok]


def _search_extra_filter(q: str) -> dict[str, Any] | None:
    tokens = _tokens(q)
    if not tokens:
        return None
    return {"$and": [{"search_keys": {"$regex": f"^{re.escape(tok)}", "$options": "i"}} for tok in tokens]}


def list_dashboard_summaries(
    db: Any, effective_user: UserAccount, *, scope: str | None, q: str
) -> list[dict[str, Any]]:
    spec = visibility_spec(effective_user)
    extra = _search_extra_filter(q)
    if scope:
        scope_filter = {"scope": str(ScopeType(scope))}
        extra = {"$and": [extra, scope_filter]} if extra else scope_filter
    dashboards = dashboards_repo.list_visible_dashboards(db, spec, extra_filter=extra)
    pinned = set(effective_user.pinned_dashboard_ids)
    return [
        {
            "id": d.id,
            "title": d.title,
            "scope": str(d.scope),
            "team_ids": list(d.team_ids),
            "always_display": d.always_display,
            "icon": d.icon,
            "sort_order": d.sort_order,
            "in_menu": d.always_display or d.id in pinned,
        }
        for d in dashboards
    ]


def get_dashboard_detail(db: Any, effective_user: UserAccount, dashboard_id: str) -> dict[str, Any]:
    """Editable resource: properties + ``widgets`` + ``version`` (no resolved items, API.md §4.3)."""
    dashboard = dashboards_repo.get_dashboard(db, dashboard_id)
    if not matches(visibility_spec(effective_user), dashboard):
        raise NotFound(dashboards_repo.COLLECTION, dashboard_id)
    return _props(dashboard, effective_user)


def _props(dashboard: Dashboard, user: UserAccount) -> dict[str, Any]:
    return {
        "id": dashboard.id,
        "title": dashboard.title,
        "description": dashboard.description,
        "scope": str(dashboard.scope),
        "team_ids": list(dashboard.team_ids),
        "owner_usernames": list(dashboard.owner_usernames),
        "always_display": dashboard.always_display,
        "icon": dashboard.icon,
        "sort_order": dashboard.sort_order,
        "orphaned": dashboard.orphaned,
        "version": dashboard.version,
        "can_edit": can_edit(user, dashboard).allowed,
        "widgets": [
            {
                "id": w.id,
                "widget_type": str(w.widget_type),
                "title": w.title,
                "grid_x": w.grid_x,
                "grid_y": w.grid_y,
                "grid_w": w.grid_w,
                "grid_h": w.grid_h,
                "catalog_item_id": w.catalog_item_id,
                "list_id": w.list_id,
            }
            for w in dashboard.widgets
        ],
    }


def _check_icon(icon: Any) -> str:
    """A Material icon name for the menu; anything else is a 400 on the ``icon`` field."""
    if not isinstance(icon, str) or not re.match(DASHBOARD_ICON_RE, icon):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Icon must be a Material icon name (lowercase letters, digits, underscores).",
            status_code=400,
            fields={"icon": ["Lowercase letters, digits and underscores only."]},
        )
    return icon


def create_dashboard(
    db: Any,
    real_user: UserAccount,
    *,
    title: str,
    description: str = "",
    scope: str = "GLOBAL",
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    always_display: bool = False,
    icon: str = "dashboard",
    set_as_user_default: bool = False,
    set_as_global_default: bool = False,
) -> Dashboard:
    scope_enum = ScopeType(scope)
    decision = can_create(real_user, scope_enum, team_ids or [])
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)
    if set_as_global_default and not has_permission(real_user, PermissionFlag.GLOBAL_ADMIN):
        raise ApiError(
            ErrorCode.PERMISSION_DENIED, "Only a Global Admin may set the app-wide default.", status_code=403
        )
    if set_as_global_default and scope_enum != ScopeType.GLOBAL:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "The app-wide default dashboard must be GLOBAL scope.", status_code=400
        )

    owners = (
        list(owner_usernames)
        if owner_usernames is not None
        else ([real_user.username] if scope_enum == ScopeType.PERSONAL else [])
    )
    keys = compute_search_keys(title, "", "", [])
    dashboard = dashboards_repo.create_dashboard(
        db,
        title=title,
        created_by=real_user.username,
        description=description,
        scope=str(scope_enum),
        team_ids=list(team_ids or []),
        owner_usernames=owners,
        always_display=always_display,
        icon=_check_icon(icon),
        search_keys=keys,
    )

    # Pinned to the creator's menu (API.md §4.3) -- always, independent of always_display/default.
    pinned = list(real_user.pinned_dashboard_ids)
    pinned.append(dashboard.id)
    update_fields: dict[str, Any] = {"pinned_dashboard_ids": pinned}
    if set_as_user_default:
        update_fields["default_dashboard_id"] = dashboard.id
    users_repo.update_user(db, real_user.id, real_user.version, **update_fields)

    if set_as_global_default:
        settings_doc = settings_repo.get_system_settings(db)
        if settings_doc is not None:
            settings_repo.set_default_global_dashboard(
                db, settings_doc.version, default_global_dashboard_id=dashboard.id, updated_by=real_user.username
            )
    return dashboard


_PATCH_FIELDS = frozenset(
    {"title", "description", "scope", "team_ids", "owner_usernames", "always_display", "sort_order", "icon"}
)


def update_dashboard_properties(
    db: Any, real_user: UserAccount, dashboard_id: str, expected_version: int, **fields: Any
) -> Dashboard:
    unknown = set(fields) - _PATCH_FIELDS
    if unknown:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"Unknown field(s): {', '.join(sorted(unknown))}.", status_code=400)
    dashboard = dashboards_repo.get_dashboard(db, dashboard_id)
    if not matches(visibility_spec(real_user), dashboard):
        raise NotFound(dashboards_repo.COLLECTION, dashboard_id)
    decision = can_edit(real_user, dashboard)
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)

    new_scope = ScopeType(fields.get("scope", dashboard.scope))
    new_team_ids = fields.get("team_ids", dashboard.team_ids)
    if "scope" in fields or "team_ids" in fields:
        create_decision = can_create(real_user, new_scope, new_team_ids or [])
        if not create_decision.allowed:
            raise ApiError(
                create_decision.error_code or ErrorCode.PERMISSION_DENIED, create_decision.reason, status_code=403
            )

    fields = dict(fields)
    if "scope" in fields:
        fields["scope"] = str(new_scope)
    if "icon" in fields:
        fields["icon"] = _check_icon(fields["icon"])
    return dashboards_repo.update_dashboard(db, dashboard_id, expected_version, updated_by=real_user.username, **fields)


def _clamp_widget(raw: dict[str, Any]) -> dict[str, Any]:
    widget_type = raw.get("widget_type")
    if widget_type not in (str(WidgetType.HOST), str(WidgetType.LIST)):
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"Invalid widget_type: {widget_type!r}.", status_code=400)
    catalog_item_id = raw.get("catalog_item_id")
    list_id = raw.get("list_id")
    if widget_type == str(WidgetType.HOST) and not catalog_item_id:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "HOST widgets require catalog_item_id.", status_code=400)
    if widget_type == str(WidgetType.LIST) and not list_id:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "LIST widgets require list_id.", status_code=400)

    grid_w = max(3, min(int(raw.get("grid_w", 4)), 12))
    grid_x = max(1, min(int(raw.get("grid_x", 1)), 12))
    if grid_x + grid_w - 1 > 12:
        grid_x = max(1, 12 - grid_w + 1)
    grid_h = max(1, min(int(raw.get("grid_h", 1)), 6))
    grid_y = max(1, int(raw.get("grid_y", 1)))
    widget_id = raw.get("id") or f"w-{uuid.uuid4().hex[:12]}"

    return {
        "id": widget_id,
        "widget_type": widget_type,
        "title": raw.get("title", "") or "",
        "grid_x": grid_x,
        "grid_y": grid_y,
        "grid_w": grid_w,
        "grid_h": grid_h,
        "catalog_item_id": catalog_item_id if widget_type == str(WidgetType.HOST) else None,
        "list_id": list_id if widget_type == str(WidgetType.LIST) else None,
    }


def replace_layout(
    db: Any, real_user: UserAccount, dashboard_id: str, expected_version: int, widgets: list[dict[str, Any]]
) -> Dashboard:
    """``PUT /api/v1/dashboards/{id}/layout``: full widget replacement (API.md §4.3)."""
    dashboard = dashboards_repo.get_dashboard(db, dashboard_id)
    if not matches(visibility_spec(real_user), dashboard):
        raise NotFound(dashboards_repo.COLLECTION, dashboard_id)
    decision = can_edit(real_user, dashboard)
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)
    if len(widgets) > MAX_WIDGETS:
        raise ApiError(
            ErrorCode.PAYLOAD_TOO_LARGE, f"A dashboard may have at most {MAX_WIDGETS} widgets.", status_code=413
        )

    clamped = [_clamp_widget(w) for w in widgets]
    targets = [w["catalog_item_id"] or w["list_id"] for w in clamped]
    repeated = sorted({t for t in targets if targets.count(t) > 1})
    if repeated:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Each item or list may appear on a dashboard only once.",
            status_code=400,
            fields={"widgets": [f"Duplicate target: {t}" for t in repeated]},
        )

    spec = visibility_spec(real_user)
    item_ids = {w["catalog_item_id"] for w in clamped if w["catalog_item_id"]}
    list_ids = {w["list_id"] for w in clamped if w["list_id"]}
    found_items = {i.id: i for i in catalog_repo.get_catalog_items_by_ids(db, sorted(item_ids))}
    found_lists = {lst.id: lst for lst in lists_repo.get_lists_by_ids(db, sorted(list_ids))}

    bad_items = [iid for iid in item_ids if iid not in found_items or not matches(spec, found_items[iid])]
    bad_lists = [lid for lid in list_ids if lid not in found_lists or not matches(spec, found_lists[lid])]
    if bad_items or bad_lists:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "One or more widgets reference an item/list that does not exist or is not visible to you.",
            status_code=400,
            fields={"catalog_item_id": bad_items, "list_id": bad_lists},
        )

    return dashboards_repo.update_dashboard(
        db, dashboard_id, expected_version, updated_by=real_user.username, widgets=clamped
    )


def delete_dashboard(db: Any, real_user: UserAccount, dashboard_id: str, expected_version: int) -> None:
    dashboard = dashboards_repo.get_dashboard(db, dashboard_id)
    if not matches(visibility_spec(real_user), dashboard):
        raise NotFound(dashboards_repo.COLLECTION, dashboard_id)
    decision = can_delete(real_user, dashboard)
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)

    settings_doc = settings_repo.get_system_settings(db)
    if settings_doc is not None and settings_doc.default_global_dashboard_id == dashboard_id:
        raise ApiError(
            ErrorCode.PROTECTED_RESOURCE, "The app-wide default dashboard cannot be deleted.", status_code=409
        )

    dashboards_repo.delete_dashboard(db, dashboard_id, expected_version)
    users_repo.remove_dashboard_references(db, dashboard_id)


__all__ = [
    "can_delete",
    "create_dashboard",
    "delete_dashboard",
    "get_dashboard_detail",
    "list_dashboard_summaries",
    "replace_layout",
    "update_dashboard_properties",
]

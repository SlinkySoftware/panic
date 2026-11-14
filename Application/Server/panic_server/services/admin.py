"""Administration composition and writes (API.md §4.7): sites, teams, zones, users, orphans,
settings. Global Admin unless noted; the admin-only gate itself is the view layer's
``IsGlobalAdmin`` permission (F1/F2), not re-checked here.
"""

from __future__ import annotations

import contextlib
from typing import Any

from panic_common.errors import ErrorCode
from panic_common.models import CatalogItem, Dashboard, EndpointList, PermissionFlag, ScopeType, UserAccount
from panic_common.rbac import has_permission
from panic_common.search_keys import search_keys as compute_search_keys
from panic_common.visibility import assign_orphan_to_user, visibility_spec
from panic_common.zones import check_item_reachability, resolve_ip_zone, validate_cidr_list
from panic_server.api.errors import ApiError
from panic_server.store.cas import iso_z
from panic_server.store.errors import NotFound
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import orphans as orphans_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo
from panic_server.store.repos._scoped import count_owned_by
from panic_server.store.sessions import delete_sessions_for_user

# ======================================================================== sites


def list_sites(db: Any) -> list[dict[str, Any]]:
    return [
        {"id": s.id, "code": s.code, "name": s.name, "description": s.description} for s in sites_repo.list_sites(db)
    ]


def create_site(db: Any, *, code: str, name: str, description: str = "") -> Any:
    return sites_repo.create_site(db, code=code, name=name, description=description)


def update_site(db: Any, site_id: str, expected_version: int, **fields: Any) -> Any:
    old = sites_repo.get_site(db, site_id)
    updated = sites_repo.update_site(db, site_id, expected_version, **fields)
    new_code = fields.get("code")
    if new_code and updated.code != old.code:
        catalog_repo.rename_site_code(db, old.code, updated.code)
    return updated


def delete_site(db: Any, site_id: str, expected_version: int) -> None:
    if len(sites_repo.list_sites(db)) <= 1:
        raise ApiError(ErrorCode.PROTECTED_RESOURCE, "The last remaining site cannot be deleted.", status_code=409)
    sites_repo.delete_site(db, site_id, expected_version)


# ======================================================================== teams


def list_teams(db: Any) -> list[dict[str, Any]]:
    return [
        {"id": t.id, "code": t.code, "name": t.name, "description": t.description} for t in teams_repo.list_teams(db)
    ]


def create_team(db: Any, *, code: str, name: str, description: str = "") -> Any:
    return teams_repo.create_team(db, code=code, name=name, description=description)


def update_team(db: Any, team_id: str, expected_version: int, **fields: Any) -> Any:
    return teams_repo.update_team(db, team_id, expected_version, **fields)


def delete_team(db: Any, team_id: str, expected_version: int) -> dict[str, dict[str, int]]:
    counts = teams_repo.delete_team(db, team_id, expected_version)
    return {
        "orphaned": {
            "catalog": counts.get("catalog_items_orphaned", 0),
            "lists": counts.get("endpoint_lists_orphaned", 0),
            "dashboards": counts.get("dashboards_orphaned", 0),
        }
    }


def get_team_members(db: Any, team_id: str, *, page: int, page_size: int) -> dict[str, Any]:
    teams_repo.get_team(db, team_id)  # 404 for an unknown team
    members = users_repo.list_users(db, team_id=team_id)
    total = len(members)
    start = max(page - 1, 0) * page_size
    page_members = members[start : start + page_size]
    return {
        "results": [user_summary(u) for u in page_members],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_next": start + page_size < total,
    }


# ======================================================================== zones


def list_zones(db: Any, effective_user: UserAccount) -> list[dict[str, Any]]:
    is_admin = has_permission(effective_user, PermissionFlag.GLOBAL_ADMIN)
    rows: list[dict[str, Any]] = []
    for z in zones_repo.list_zones(db):
        if is_admin:
            rows.append(
                {
                    "id": z.id,
                    "name": z.name,
                    "builtin": z.builtin,
                    "description": z.description,
                    "priority": z.priority,
                    "cidrs": list(z.cidrs),
                    "version": z.version,
                }
            )
        else:
            rows.append({"id": z.id, "name": z.name, "builtin": z.builtin})
    return rows


def create_zone(
    db: Any, *, name: str, description: str = "", priority: int = 100, cidrs: list[str] | None = None
) -> Any:
    try:
        clean_cidrs = validate_cidr_list(cidrs or [])
    except ValueError as e:
        raise ApiError(ErrorCode.INVALID_CIDR, str(e), status_code=400) from e
    return zones_repo.create_zone(db, name=name, description=description, priority=priority, cidrs=clean_cidrs)


def update_zone(db: Any, zone_id: str, expected_version: int, **fields: Any) -> Any:
    if "cidrs" in fields and fields["cidrs"] is not None:
        try:
            fields["cidrs"] = validate_cidr_list(fields["cidrs"])
        except ValueError as e:
            raise ApiError(ErrorCode.INVALID_CIDR, str(e), status_code=400) from e
    if zone_id == zones_repo.DEFAULT_ZONE_ID and fields.get("priority") is not None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "The built-in Default zone's priority cannot be changed.", status_code=400
        )
    try:
        return zones_repo.update_zone(db, zone_id, expected_version, **fields)
    except ValueError as e:
        raise ApiError(ErrorCode.VALIDATION_ERROR, str(e), status_code=400) from e


def delete_zone(db: Any, zone_id: str, expected_version: int) -> None:
    try:
        zones_repo.delete_zone(db, zone_id, expected_version)
    except ValueError as e:
        raise ApiError(ErrorCode.PROTECTED_RESOURCE, str(e), status_code=409) from e


def test_ip(db: Any, ip: str) -> dict[str, Any]:
    """``POST /api/v1/zones/test-ip``: resolution + reachable/blocked counts only (F5: never the
    full item list)."""
    zones = zones_repo.list_zones(db)
    result = resolve_ip_zone(ip, zones)
    if not result.valid_ip:
        raise ApiError(ErrorCode.INVALID_IP_ADDRESS, f"{ip!r} is not a valid IP address.", status_code=400)

    winning = result.winning_zone
    zone_source = "CIDR" if winning is not None else "DEFAULT"
    if winning is None:
        try:
            winning = zones_repo.get_zone(db, zones_repo.DEFAULT_ZONE_ID)
        except NotFound:
            winning = None

    items = catalog_repo.list_all_catalog_items(db)
    reachable_count = sum(1 for i in items if check_item_reachability(i, winning).reachable)
    blocked_count = len(items) - reachable_count

    return {
        "resolution": {
            "winning_zone": {"id": winning.id, "name": winning.name} if winning is not None else None,
            "zone_source": zone_source,
            "matched_cidr": result.matched_cidr,
            "candidates": [c.model_dump(mode="json") for c in result.candidates],
        },
        "reachable_count": reachable_count,
        "blocked_count": blocked_count,
    }


# ======================================================================== users


def user_summary(u: UserAccount) -> dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "auth_source": str(u.auth_source),
        "permissions": [str(p) for p in u.permissions],
        "team_ids": list(u.team_ids),
        "disabled": u.disabled,
        "last_login_at": u.last_login_at,
        "version": u.version,
    }


def list_users(
    db: Any,
    *,
    q: str,
    permission: str | None,
    team_id: str | None,
    disabled: bool | None,
) -> list[dict[str, Any]]:
    users = users_repo.list_users(db, team_id=team_id or None, permission=permission or None, disabled=disabled)
    if q:
        needle = q.strip().lower()
        users = [u for u in users if needle in u.username.lower() or needle in u.display_name.lower()]
    return [user_summary(u) for u in users]


def get_user_detail(db: Any, user_id: str) -> dict[str, Any]:
    user = users_repo.get_user(db, user_id)
    owned_counts = {
        "catalog": count_owned_by(db, catalog_repo.COLLECTION, user.username),
        "lists": count_owned_by(db, lists_repo.COLLECTION, user.username),
        "dashboards": count_owned_by(db, dashboards_repo.COLLECTION, user.username),
    }
    return {**user_summary(user), "owned_counts": owned_counts}


def create_user(
    db: Any,
    *,
    username: str,
    display_name: str | None = None,
    permissions: list[str] | None = None,
    team_ids: list[str] | None = None,
) -> UserAccount:
    """``POST /api/v1/users``: pre-provision, no password (local sign-in stays bootstrap-admin only)."""
    name = display_name or username
    keys = compute_search_keys(name, "", "", [], username)
    return users_repo.create_user(
        db,
        username=username,
        display_name=name,
        default_remote_user=username,
        permissions=list(permissions or []),
        team_ids=list(team_ids or []),
        search_keys=keys,
    )


_USER_PATCH_FIELDS = frozenset({"display_name", "permissions", "team_ids", "disabled"})


def update_user(db: Any, user_id: str, expected_version: int, **fields: Any) -> UserAccount:
    """``PATCH /api/v1/users/{id}``: the only way to change permissions/team membership (F1).

    Refuses to demote or disable the last enabled manual ``GLOBAL_ADMIN`` (``409
    PROTECTED_RESOURCE``). Disabling flushes sessions and recomputes orphans on the user's
    PERSONAL resources; re-enabling recomputes them again.
    """
    unknown = set(fields) - _USER_PATCH_FIELDS
    if unknown:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"Unknown field(s): {', '.join(sorted(unknown))}.", status_code=400)

    target = users_repo.get_user(db, user_id)
    was_admin = PermissionFlag.GLOBAL_ADMIN in target.permissions
    will_be_disabled = bool(fields.get("disabled", target.disabled))
    will_be_admin = ("GLOBAL_ADMIN" in fields["permissions"]) if "permissions" in fields else was_admin
    losing_admin_status = was_admin and not target.disabled and (will_be_disabled or not will_be_admin)
    if losing_admin_status and users_repo.count_enabled_admins(db) <= 1:
        raise ApiError(
            ErrorCode.PROTECTED_RESOURCE,
            "The last enabled Global Admin cannot be demoted or disabled.",
            status_code=409,
        )

    updated = users_repo.update_user(db, user_id, expected_version, **fields)

    disabling_now = "disabled" in fields and bool(fields["disabled"]) and not target.disabled
    enabling_now = "disabled" in fields and not fields["disabled"] and target.disabled
    if disabling_now:
        delete_sessions_for_user(updated.id)
    if disabling_now or enabling_now:
        enabled_usernames = [u.username for u in users_repo.list_users(db, disabled=False)]
        orphans_repo.recompute_orphans_on_user_change(db, enabled_usernames)

    return updated


# ======================================================================== orphans

_ORPHAN_REPOS: dict[str, tuple[str, Any]] = {
    "catalog": (catalog_repo.COLLECTION, catalog_repo),
    "list": (lists_repo.COLLECTION, lists_repo),
    "dashboard": (dashboards_repo.COLLECTION, dashboards_repo),
}
_COLLECTION_TO_KIND = {v[0]: k for k, v in _ORPHAN_REPOS.items()}


def list_orphans(db: Any, *, kind: str | None, q: str, page: int, page_size: int) -> dict[str, Any]:
    if kind is not None and kind not in _ORPHAN_REPOS:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"Unknown kind: {kind!r}.", status_code=400)
    collections = [_ORPHAN_REPOS[kind][0]] if kind else [v[0] for v in _ORPHAN_REPOS.values()]

    rows: list[dict[str, Any]] = []
    for collection in collections:
        for doc in orphans_repo.list_orphans(db, collection):
            title = doc.get("title", "")
            if q and q.strip().lower() not in title.lower():
                continue
            updated_at = doc.get("updated_at")
            scope = doc.get("scope")
            rows.append(
                {
                    "kind": _COLLECTION_TO_KIND[collection],
                    "id": doc["_id"],
                    "title": title,
                    "scope": scope,
                    "former_team_ids": doc.get("team_ids") if scope == "TEAM" else None,
                    "former_owners": doc.get("owner_usernames") if scope == "PERSONAL" else None,
                    "updated_at": iso_z(updated_at) if updated_at is not None else None,
                }
            )
    rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    total = len(rows)
    start = max(page - 1, 0) * page_size
    page_rows = rows[start : start + page_size]
    return {
        "results": page_rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_next": start + page_size < total,
    }


def assign_orphan(db: Any, real_user: UserAccount, kind: str, item_id: str, target_username: str) -> dict[str, Any]:
    """``POST /api/v1/admin/orphans/{kind}/{id}/assign``: the orphan becomes ``PERSONAL`` for an
    enabled user (``panic_common.visibility.assign_orphan_to_user``)."""
    if kind not in _ORPHAN_REPOS:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"Unknown kind: {kind!r}.", status_code=400)

    target = users_repo.get_user_by_username(db, target_username)
    if target is None or target.disabled:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "The target user must exist and be enabled.", status_code=400)

    resource: CatalogItem | EndpointList | Dashboard
    if kind == "catalog":
        resource = catalog_repo.get_catalog_item(db, item_id)
    elif kind == "list":
        resource = lists_repo.get_list(db, item_id)
    else:
        resource = dashboards_repo.get_dashboard(db, item_id)
    if not resource.orphaned:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "This resource is not orphaned.", status_code=400)

    dropped_item_ids: list[str] = []
    fields: dict[str, Any]
    updated: CatalogItem | EndpointList | Dashboard
    if kind == "list":
        assert isinstance(resource, EndpointList)
        personal_ids = [
            i.id
            for i in catalog_repo.list_visible_catalog_items(db, visibility_spec(target))
            if i.scope == ScopeType.PERSONAL
        ]
        assignment = assign_orphan_to_user(
            target.username, item_ids=resource.item_ids, personal_item_ids_for_user=personal_ids
        )
        dropped_item_ids = list(assignment.dropped_item_ids or [])
        fields = {
            "scope": str(assignment.scope),
            "team_ids": list(assignment.team_ids),
            "owner_usernames": list(assignment.owner_usernames),
            "orphaned": assignment.orphaned,
            "item_ids": list(assignment.kept_item_ids or []),
        }
        updated = lists_repo.update_list(db, item_id, resource.version, updated_by=real_user.username, **fields)
    else:
        assignment = assign_orphan_to_user(target.username)
        fields = {
            "scope": str(assignment.scope),
            "team_ids": list(assignment.team_ids),
            "owner_usernames": list(assignment.owner_usernames),
            "orphaned": assignment.orphaned,
        }
        if kind == "catalog":
            updated = catalog_repo.update_catalog_item(
                db, item_id, resource.version, updated_by=real_user.username, **fields
            )
        else:
            updated = dashboards_repo.update_dashboard(
                db, item_id, resource.version, updated_by=real_user.username, **fields
            )

    return {"id": updated.id, "scope": str(updated.scope), "dropped_item_ids": dropped_item_ids}


# ======================================================================== settings


def get_settings(db: Any) -> dict[str, Any]:
    doc = settings_repo.get_system_settings(db)
    if doc is None or not doc.default_global_dashboard_id:
        return {"default_global_dashboard": None, "version": doc.version if doc else 0}
    title = None
    with contextlib.suppress(NotFound):
        title = dashboards_repo.get_dashboard(db, doc.default_global_dashboard_id).title
    return {"default_global_dashboard": {"id": doc.default_global_dashboard_id, "title": title}, "version": doc.version}


def update_settings(db: Any, real_user: UserAccount, expected_version: int, default_global_dashboard_id: str) -> Any:
    dashboard = dashboards_repo.get_dashboard(db, default_global_dashboard_id)
    if dashboard.scope != ScopeType.GLOBAL:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "The app-wide default dashboard must be GLOBAL scope.", status_code=400
        )
    return settings_repo.set_default_global_dashboard(
        db, expected_version, default_global_dashboard_id=default_global_dashboard_id, updated_by=real_user.username
    )


__all__ = [
    "assign_orphan",
    "create_site",
    "create_team",
    "create_user",
    "create_zone",
    "delete_site",
    "delete_team",
    "delete_zone",
    "get_settings",
    "get_team_members",
    "get_user_detail",
    "list_orphans",
    "list_sites",
    "list_teams",
    "list_users",
    "list_zones",
    "test_ip",
    "update_settings",
    "update_site",
    "update_team",
    "update_user",
    "update_zone",
    "user_summary",
]

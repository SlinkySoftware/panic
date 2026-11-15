"""``/api/v1/catalog`` composition and writes (API.md §4.5).

Visibility is always ``panic_common.visibility.matches``/``VisibilitySpec`` (the Stage 6 pure
definition) -- never ``panic_common.rbac.is_visible_in_scope``, which DATA_MODEL.md §5 keeps only
as the parity test's in-memory comparison baseline, not for production enforcement (its PERSONAL
branch is deliberately more permissive: "empty owner_usernames -> visible to everyone", a rule
that predates orphan handling and would wrongly expose an orphaned PERSONAL item).
"""

from __future__ import annotations

import re
from typing import Any

from panic_common.errors import ErrorCode
from panic_common.hygiene import check_credential_hygiene, normalize_target
from panic_common.models import CatalogItem, PermissionFlag, Protocol, ScopeType, SecurityZone, UserAccount
from panic_common.rbac import has_permission
from panic_common.search_keys import search_keys as compute_search_keys
from panic_common.visibility import Decision, can_create, can_edit, matches, visibility_spec
from panic_server.api.errors import ApiError
from panic_server.services.launch import build_item_view
from panic_server.store.errors import NotFound
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import zones as zones_repo

_ALLOWED_SORTS = frozenset({"title", "-updated_at", "protocol", "site"})
_MAX_TAGS = 32


def _sort_spec(sort: str) -> tuple[str, bool]:
    if sort not in _ALLOWED_SORTS:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"Invalid sort: {sort!r}.", status_code=400)
    return (sort[1:], True) if sort.startswith("-") else (sort, False)


def _tokens(q: str) -> list[str]:
    return [tok[:64] for tok in q.split()[:8] if tok]


def _search_extra_filter(q: str) -> dict[str, Any] | None:
    tokens = _tokens(q)
    if not tokens:
        return None
    return {"$and": [{"search_keys": {"$regex": f"^{re.escape(tok)}", "$options": "i"}} for tok in tokens]}


def can_delete(user: UserAccount, resource: Any) -> Decision:
    """Like ``can_edit``, except a visible orphan may be *deleted* (never edited) by a Global
    Admin (DATA_MODEL.md §5.1/§6: "Global Admins may only assign to a user or delete")."""
    if resource.orphaned:
        if has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.ORPHANED_RESOURCE,
            reason="Orphaned resources may only be deleted by a Global Admin, or assigned to a user.",
        )
    return can_edit(user, resource)


def list_catalog(
    db: Any,
    effective_user: UserAccount,
    active_zone: SecurityZone | None,
    *,
    group: str | None,
    protocol: str | None,
    site: str | None,
    zone_id: str | None,
    team_id: str | None,
    q: str,
    sort: str,
) -> list[dict[str, Any]]:
    field, reverse = _sort_spec(sort)
    spec = visibility_spec(effective_user)

    extra: dict[str, Any] = {}
    if protocol:
        extra["protocol"] = protocol
    if site:
        extra["site"] = site
    if zone_id:
        extra["zone_ids"] = zone_id
    if team_id:
        extra["team_ids"] = team_id
    search_filter = _search_extra_filter(q)
    if search_filter:
        extra = {"$and": [extra, search_filter]} if extra else search_filter

    items = catalog_repo.list_visible_catalog_items(db, spec, extra_filter=extra or None)
    if group == "shared":
        items = [i for i in items if i.scope != ScopeType.PERSONAL]
    elif group == "personal":
        items = [i for i in items if i.scope == ScopeType.PERSONAL]

    items.sort(key=lambda i: str(getattr(i, field)).lower(), reverse=reverse)

    needs_zones = any(i.zone_ids for i in items)
    zones_by_id = {z.id: z for z in zones_repo.list_zones(db)} if needs_zones else {}

    rows: list[dict[str, Any]] = []
    for item in items:
        view = build_item_view(item, caller=effective_user, active_zone=active_zone, zones_by_id=zones_by_id)
        view["can_edit"] = can_edit(effective_user, item).allowed
        view["version"] = item.version
        view["team_ids"] = list(item.team_ids)  # the shared card's Teams column
        rows.append(view)
    return rows


def _full_view(item: CatalogItem, user: UserAccount) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "protocol": str(item.protocol),
        "host": item.host,
        "port": item.port,
        "site": item.site,
        "path_or_args": item.path_or_args,
        "custom_uri": item.custom_uri,
        "account_override": item.account_override,
        "tags": list(item.tags),
        "normalized_key": item.normalized_key,
        "scope": str(item.scope),
        "team_ids": list(item.team_ids),
        "owner_usernames": list(item.owner_usernames),
        "zone_ids": list(item.zone_ids),
        "orphaned": item.orphaned,
        "version": item.version,
        "can_edit": can_edit(user, item).allowed,
    }


def get_catalog_item_detail(db: Any, effective_user: UserAccount, item_id: str) -> dict[str, Any]:
    item = catalog_repo.get_catalog_item(db, item_id)
    if not matches(visibility_spec(effective_user), item):
        raise NotFound(catalog_repo.COLLECTION, item_id)
    return _full_view(item, effective_user)


def _visible_duplicate(db: Any, user: UserAccount, normalized_key: str, scope: ScopeType) -> CatalogItem | None:
    """F5: report a duplicate only when a copy is *visible* to the caller."""
    existing = catalog_repo.find_by_normalized_key(db, normalized_key, str(scope))
    if existing is None or not matches(visibility_spec(user), existing):
        return None
    return existing


def preview_catalog_item(
    db: Any,
    user: UserAccount,
    *,
    protocol: str,
    host: str,
    port: int | None,
    path_or_args: str,
    account_override: str,
    custom_uri: str,
    scope: str,
) -> dict[str, Any]:
    """``POST /api/v1/catalog/preview``: normalize/hygiene/duplicate preview, no persistence (F5)."""
    protocol_enum = Protocol(protocol)
    scope_enum = ScopeType(scope)
    normalized_key, clean_host, resolved_port = normalize_target(protocol_enum, host, port, path_or_args)
    hygiene_errors = check_credential_hygiene(protocol_enum, host, path_or_args, account_override, custom_uri)
    duplicate = _visible_duplicate(db, user, normalized_key, scope_enum)
    return {
        "normalized_key": normalized_key,
        "resolved_host": clean_host,
        "resolved_port": resolved_port,
        "hygiene_passed": not hygiene_errors,
        "hygiene_errors": hygiene_errors,
        "duplicate": {"id": duplicate.id, "title": duplicate.title} if duplicate is not None else None,
    }


def create_catalog_item(
    db: Any,
    real_user: UserAccount,
    *,
    title: str,
    protocol: str,
    host: str,
    port: int | None = None,
    site: str = "2SYA",
    path_or_args: str = "",
    custom_uri: str = "",
    account_override: str = "",
    description: str = "",
    tags: list[str] | None = None,
    scope: str = "GLOBAL",
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    zone_ids: list[str] | None = None,
    force_allow_duplicate: bool = False,
) -> CatalogItem:
    protocol_enum = Protocol(protocol)
    scope_enum = ScopeType(scope)
    tags = list(tags or [])
    if len(tags) > _MAX_TAGS:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"At most {_MAX_TAGS} tags are allowed.", status_code=400)

    decision = can_create(real_user, scope_enum, team_ids or [])
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)

    hygiene_errors = check_credential_hygiene(protocol_enum, host, path_or_args, account_override, custom_uri)
    if hygiene_errors:
        raise ApiError(
            ErrorCode.CREDENTIAL_HYGIENE_VIOLATION,
            "Credential hygiene violation.",
            status_code=400,
            hygiene_errors=hygiene_errors,
        )

    normalized_key, clean_host, _resolved_port = normalize_target(protocol_enum, host, port, path_or_args)
    if not force_allow_duplicate:
        existing = _visible_duplicate(db, real_user, normalized_key, scope_enum)
        if existing is not None:
            raise ApiError(
                ErrorCode.DUPLICATE_CATALOG_ITEM,
                "An item with this target already exists. Resend with force_allow_duplicate to add it anyway.",
                status_code=409,
                existing_item={"id": existing.id, "title": existing.title},
            )

    owners = (
        list(owner_usernames)
        if owner_usernames is not None
        else ([real_user.username] if scope_enum == ScopeType.PERSONAL else [])
    )
    keys = compute_search_keys(title, clean_host, site, tags)
    return catalog_repo.create_catalog_item(
        db,
        title=title,
        protocol=str(protocol_enum),
        host=clean_host,
        normalized_key=normalized_key,
        created_by=real_user.username,
        description=description,
        port=port,
        site=site,
        path_or_args=path_or_args,
        custom_uri=custom_uri,
        account_override=account_override,
        tags=tags,
        scope=str(scope_enum),
        team_ids=list(team_ids or []),
        owner_usernames=owners,
        zone_ids=list(zone_ids or []),
        search_keys=keys,
    )


def update_catalog_item(
    db: Any,
    real_user: UserAccount,
    item_id: str,
    expected_version: int,
    *,
    force_allow_duplicate: bool = False,
    **fields: Any,
) -> CatalogItem:
    item = catalog_repo.get_catalog_item(db, item_id)
    if not matches(visibility_spec(real_user), item):
        raise NotFound(catalog_repo.COLLECTION, item_id)
    decision = can_edit(real_user, item)
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)

    if "tags" in fields and fields["tags"] is not None and len(fields["tags"]) > _MAX_TAGS:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"At most {_MAX_TAGS} tags are allowed.", status_code=400)

    protocol_enum = Protocol(fields.get("protocol", item.protocol))
    host = fields.get("host", item.host)
    port = fields.get("port", item.port)
    path_or_args = fields.get("path_or_args", item.path_or_args)
    account_override = fields.get("account_override", item.account_override)
    custom_uri = fields.get("custom_uri", item.custom_uri)
    site = fields.get("site", item.site)
    title = fields.get("title", item.title)
    tags = fields.get("tags", item.tags)
    scope_enum = ScopeType(fields.get("scope", item.scope))

    hygiene_errors = check_credential_hygiene(protocol_enum, host, path_or_args, account_override, custom_uri)
    if hygiene_errors:
        raise ApiError(
            ErrorCode.CREDENTIAL_HYGIENE_VIOLATION,
            "Credential hygiene violation.",
            status_code=400,
            hygiene_errors=hygiene_errors,
        )

    normalized_key, clean_host, _resolved_port = normalize_target(protocol_enum, host, port, path_or_args)
    if normalized_key != item.normalized_key and not force_allow_duplicate:
        existing = _visible_duplicate(db, real_user, normalized_key, scope_enum)
        if existing is not None and existing.id != item.id:
            raise ApiError(
                ErrorCode.DUPLICATE_CATALOG_ITEM,
                "An item with this target already exists. Resend with force_allow_duplicate to add it anyway.",
                status_code=409,
                existing_item={"id": existing.id, "title": existing.title},
            )

    fields = dict(fields)
    fields["protocol"] = str(protocol_enum)
    fields["host"] = clean_host
    fields["normalized_key"] = normalized_key
    fields["scope"] = str(scope_enum)
    fields["search_keys"] = compute_search_keys(title, clean_host, site, tags)
    return catalog_repo.update_catalog_item(db, item_id, expected_version, updated_by=real_user.username, **fields)


def delete_catalog_item(db: Any, real_user: UserAccount, item_id: str, expected_version: int) -> None:
    item = catalog_repo.get_catalog_item(db, item_id)
    if not matches(visibility_spec(real_user), item):
        raise NotFound(catalog_repo.COLLECTION, item_id)
    decision = can_delete(real_user, item)
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)
    catalog_repo.delete_catalog_item(db, item_id, expected_version)


__all__ = [
    "can_delete",
    "create_catalog_item",
    "delete_catalog_item",
    "get_catalog_item_detail",
    "list_catalog",
    "preview_catalog_item",
    "update_catalog_item",
]

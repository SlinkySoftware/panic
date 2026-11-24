"""``/api/v1/catalog`` composition and writes (API.md §4.5).

Visibility is always ``panic_common.visibility.matches``/``VisibilitySpec`` (the pure
definition) -- never ``panic_common.rbac.is_visible_in_scope``, which DATA_MODEL.md §5 keeps only
as the parity test's in-memory comparison baseline, not for production enforcement (its PERSONAL
branch is deliberately more permissive: "empty owner_usernames -> visible to everyone", a rule
that predates orphan handling and would wrongly expose an orphaned PERSONAL item).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from panic_common.errors import ErrorCode
from panic_common.hygiene import check_connections, check_item_hygiene, normalize_connections, normalize_target
from panic_common.models import CatalogItem, Connection, PermissionFlag, ScopeType, SecurityZone, UserAccount
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


def parse_connections(raw: Any) -> list[Connection]:
    """The request's ``connections`` array -> models; ``400 VALIDATION_ERROR`` on ``fields.connections``."""

    def invalid(message: str) -> ApiError:
        return ApiError(ErrorCode.VALIDATION_ERROR, message, status_code=400, fields={"connections": [message]})

    if not isinstance(raw, list):
        raise invalid("connections must be a list of {protocol, port, path_or_args, custom_uri}.")
    try:
        connections = [Connection.model_validate(c) for c in raw]
    except ValidationError:
        raise invalid("Each connection needs a protocol of URL, SSH, RDP or LOCAL_APP.") from None
    errors = check_connections(connections)
    if errors:
        raise invalid(" ".join(errors))
    return connections


def _hygiene_or_raise(host: str, account_override: str, connections: list[Connection]) -> None:
    hygiene_errors = check_item_hygiene(host, account_override, connections)
    if hygiene_errors:
        raise ApiError(
            ErrorCode.CREDENTIAL_HYGIENE_VIOLATION,
            "Credential hygiene violation.",
            status_code=400,
            hygiene_errors=hygiene_errors,
        )


def _duplicate_error(existing: CatalogItem) -> ApiError:
    return ApiError(
        ErrorCode.DUPLICATE_CATALOG_ITEM,
        "An item with this target already exists. Resend with force_allow_duplicate to add it anyway.",
        status_code=409,
        existing_item={"id": existing.id, "title": existing.title},
    )


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
        extra["connections.protocol"] = protocol
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

    def sort_key(i: CatalogItem) -> str:
        return str(i.primary.protocol if field == "protocol" else getattr(i, field)).lower()

    items.sort(key=sort_key, reverse=reverse)

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
        "host": item.host,
        "connections": [c.model_dump(mode="json") for c in item.connections],
        "site": item.site,
        "account_override": item.account_override,
        "tags": list(item.tags),
        "normalized_keys": list(item.normalized_keys),
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


def _visible_duplicate(
    db: Any, user: UserAccount, normalized_keys: list[str], scope: ScopeType, *, exclude_id: str = ""
) -> CatalogItem | None:
    """F5: report a duplicate (any shared connection key) only when a copy is *visible* to the caller."""
    spec = visibility_spec(user)
    for existing in catalog_repo.find_by_normalized_keys(db, normalized_keys, str(scope)):
        if existing.id != exclude_id and matches(spec, existing):
            return existing
    return None


def preview_catalog_item(
    db: Any,
    user: UserAccount,
    *,
    host: str,
    connections: list[Connection],
    account_override: str,
    scope: str,
    exclude_id: str = "",
) -> dict[str, Any]:
    """``POST /api/v1/catalog/preview``: normalize/hygiene/duplicate preview, no persistence (F5)."""
    scope_enum = ScopeType(scope)
    normalized_keys, clean_host, ordered = normalize_connections(host, connections)
    _key, _host, resolved_port = normalize_target(ordered[0].protocol, clean_host, ordered[0].port)
    hygiene_errors = check_item_hygiene(host, account_override, ordered)
    duplicate = _visible_duplicate(db, user, normalized_keys, scope_enum, exclude_id=exclude_id)
    return {
        "normalized_keys": normalized_keys,
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
    host: str,
    connections: list[Connection],
    site: str = "2SYA",
    account_override: str = "",
    description: str = "",
    tags: list[str] | None = None,
    scope: str = "GLOBAL",
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    zone_ids: list[str] | None = None,
    force_allow_duplicate: bool = False,
) -> CatalogItem:
    scope_enum = ScopeType(scope)
    tags = list(tags or [])
    if len(tags) > _MAX_TAGS:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"At most {_MAX_TAGS} tags are allowed.", status_code=400)

    decision = can_create(real_user, scope_enum, team_ids or [])
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)

    _hygiene_or_raise(host, account_override, connections)

    normalized_keys, clean_host, ordered = normalize_connections(host, connections)
    if not force_allow_duplicate:
        existing = _visible_duplicate(db, real_user, normalized_keys, scope_enum)
        if existing is not None:
            raise _duplicate_error(existing)

    owners = (
        list(owner_usernames)
        if owner_usernames is not None
        else ([real_user.username] if scope_enum == ScopeType.PERSONAL else [])
    )
    keys = compute_search_keys(title, clean_host, site, tags)
    return catalog_repo.create_catalog_item(
        db,
        title=title,
        host=clean_host,
        connections=[c.model_dump(mode="json") for c in ordered],
        normalized_keys=normalized_keys,
        created_by=real_user.username,
        description=description,
        site=site,
        account_override=account_override,
        tags=tags,
        scope=str(scope_enum),
        team_ids=list(team_ids or []),
        owner_usernames=owners,
        zone_ids=list(zone_ids or []),
        search_keys=keys,
    )


#: Fields a ``PATCH /catalog/{id}`` may set (anything else in the body is ignored).
_UPDATABLE = frozenset(
    {"title", "description", "host", "connections", "site", "account_override", "tags", "scope", "team_ids", "zone_ids"}
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

    fields = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if "tags" in fields and fields["tags"] is not None and len(fields["tags"]) > _MAX_TAGS:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"At most {_MAX_TAGS} tags are allowed.", status_code=400)

    connections = parse_connections(fields["connections"]) if "connections" in fields else item.connections
    host = fields.get("host", item.host)
    account_override = fields.get("account_override", item.account_override)
    site = fields.get("site", item.site)
    title = fields.get("title", item.title)
    tags = fields.get("tags", item.tags)
    scope_enum = ScopeType(fields.get("scope", item.scope))

    _hygiene_or_raise(host, account_override, connections)

    normalized_keys, clean_host, ordered = normalize_connections(host, connections)
    if not set(normalized_keys) <= set(item.normalized_keys) and not force_allow_duplicate:
        existing = _visible_duplicate(db, real_user, normalized_keys, scope_enum, exclude_id=item.id)
        if existing is not None:
            raise _duplicate_error(existing)

    fields["connections"] = [c.model_dump(mode="json") for c in ordered]
    fields["host"] = clean_host
    fields["normalized_keys"] = normalized_keys
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
    "parse_connections",
    "preview_catalog_item",
    "update_catalog_item",
]

"""``/api/v1/lists`` composition and writes (API.md §4.6).

**F6** (list saves accepted invisible/wrong-scope item ids): ``panic_common.rbac.validate_list_item_scopes``
only checks scope equality against whatever ``catalog`` list it is given -- it has no visibility
notion of its own. The fix is entirely at this call site: the ``catalog`` argument passed to it is
first filtered down to items *visible to the editor* (``panic_common.visibility.matches``), so an
id that is invisible to the editor looks exactly like an id that does not exist at all (the
function's own "does not exist" branch), and a visible-but-wrong-scope id still hits its scope
branch -- giving two distinct, already-defined error messages this module turns into
``VALIDATION_ERROR``/``SCOPE_MISMATCH`` respectively.
"""

from __future__ import annotations

import re
from typing import Any

from django.conf import settings as django_settings

from panic_common.errors import ErrorCode
from panic_common.models import EndpointList, PermissionFlag, ScopeType, UserAccount
from panic_common.rbac import has_permission, validate_list_item_scopes
from panic_common.search_keys import search_keys as compute_search_keys
from panic_common.visibility import Decision, can_create, can_edit, matches, visibility_spec
from panic_server.api.errors import ApiError
from panic_server.services.launch import build_item_view
from panic_server.store.errors import NotFound
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import zones as zones_repo

_ALLOWED_SORTS = frozenset({"title", "-updated_at"})


def can_delete(user: UserAccount, resource: Any) -> Decision:
    """List/dashboard sibling of ``services.catalog.can_delete`` -- see its docstring."""
    if resource.orphaned:
        if has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.ORPHANED_RESOURCE,
            reason="Orphaned resources may only be deleted by a Global Admin, or assigned to a user.",
        )
    return can_edit(user, resource)


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


def list_lists(db: Any, effective_user: UserAccount, *, group: str | None, q: str, sort: str) -> list[dict[str, Any]]:
    field, reverse = _sort_spec(sort)
    spec = visibility_spec(effective_user)
    extra = _search_extra_filter(q)
    all_lists = lists_repo.list_visible_lists(db, spec, extra_filter=extra)
    if group == "shared":
        all_lists = [lst for lst in all_lists if lst.scope != ScopeType.PERSONAL]
    elif group == "personal":
        all_lists = [lst for lst in all_lists if lst.scope == ScopeType.PERSONAL]
    all_lists.sort(key=lambda lst: str(getattr(lst, field)).lower(), reverse=reverse)
    return [
        {
            "id": lst.id,
            "title": lst.title,
            "description": lst.description,
            "scope": str(lst.scope),
            "team_ids": list(lst.team_ids),
            "item_count": len(lst.item_ids),
            "version": lst.version,
            "can_edit": can_edit(effective_user, lst).allowed,
        }
        for lst in all_lists
    ]


def get_list_detail(db: Any, context: Any, list_id: str) -> dict[str, Any]:
    effective = context.effective_user
    lst = lists_repo.get_list(db, list_id)
    spec = visibility_spec(effective)
    if not matches(spec, lst):
        raise NotFound(lists_repo.COLLECTION, list_id)

    max_items = django_settings.PANIC_LIST_MAX_ITEMS
    shown_ids = lst.item_ids[:max_items]
    found = {i.id: i for i in catalog_repo.get_catalog_items_by_ids(db, shown_ids)}
    visible_items = [found[iid] for iid in shown_ids if iid in found and matches(spec, found[iid])]

    needs_zones = any(i.zone_ids for i in visible_items)
    zones_by_id = {z.id: z for z in zones_repo.list_zones(db)} if needs_zones else {}
    items_view = [
        build_item_view(i, caller=effective, active_zone=context.zone, zones_by_id=zones_by_id) for i in visible_items
    ]

    return {
        "id": lst.id,
        "title": lst.title,
        "description": lst.description,
        "scope": str(lst.scope),
        "team_ids": list(lst.team_ids),
        "owner_usernames": list(lst.owner_usernames),
        "item_ids": [i["id"] for i in items_view],
        "items": items_view,
        "orphaned": lst.orphaned,
        "version": lst.version,
        "can_edit": can_edit(effective, lst).allowed,
    }


def _validate_item_ids(db: Any, editor: UserAccount, scope: ScopeType, item_ids: list[str]) -> None:
    """F6: every id must exist, be visible to ``editor``, and match ``scope`` exactly."""
    if len(item_ids) > django_settings.PANIC_LIST_MAX_ITEMS:
        raise ApiError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"A list may contain at most {django_settings.PANIC_LIST_MAX_ITEMS} items.",
            status_code=413,
        )
    found = catalog_repo.get_catalog_items_by_ids(db, list(set(item_ids)))
    spec = visibility_spec(editor)
    visible_catalog = [i for i in found if matches(spec, i)]
    ok, errors = validate_list_item_scopes(scope, item_ids, visible_catalog)
    if not ok:
        code = ErrorCode.SCOPE_MISMATCH if any("cannot be added" in e for e in errors) else ErrorCode.VALIDATION_ERROR
        raise ApiError(code, "One or more list items failed validation.", status_code=400, errors=errors)


def create_list(
    db: Any,
    real_user: UserAccount,
    *,
    title: str,
    description: str = "",
    scope: str = "GLOBAL",
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    item_ids: list[str] | None = None,
) -> EndpointList:
    scope_enum = ScopeType(scope)
    decision = can_create(real_user, scope_enum, team_ids or [])
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)
    item_ids = list(item_ids or [])
    _validate_item_ids(db, real_user, scope_enum, item_ids)
    owners = (
        list(owner_usernames)
        if owner_usernames is not None
        else ([real_user.username] if scope_enum == ScopeType.PERSONAL else [])
    )
    keys = compute_search_keys(title, "", "", [])
    return lists_repo.create_list(
        db,
        title=title,
        created_by=real_user.username,
        description=description,
        scope=str(scope_enum),
        team_ids=list(team_ids or []),
        owner_usernames=owners,
        item_ids=item_ids,
        search_keys=keys,
    )


def replace_list(
    db: Any,
    real_user: UserAccount,
    list_id: str,
    expected_version: int,
    *,
    title: str,
    description: str = "",
    scope: str,
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    item_ids: list[str],
) -> EndpointList:
    """``PUT /api/v1/lists/{id}``: full replacement, the only reorder path (If-Match required)."""
    lst = lists_repo.get_list(db, list_id)
    if not matches(visibility_spec(real_user), lst):
        raise NotFound(lists_repo.COLLECTION, list_id)
    decision = can_edit(real_user, lst)
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)

    scope_enum = ScopeType(scope)
    _validate_item_ids(db, real_user, scope_enum, item_ids)
    owners = list(owner_usernames) if owner_usernames is not None else list(lst.owner_usernames)
    keys = compute_search_keys(title, "", "", [])
    return lists_repo.update_list(
        db,
        list_id,
        expected_version,
        updated_by=real_user.username,
        title=title,
        description=description,
        scope=str(scope_enum),
        team_ids=list(team_ids or []),
        owner_usernames=owners,
        item_ids=list(item_ids),
        search_keys=keys,
    )


def delete_list(db: Any, real_user: UserAccount, list_id: str, expected_version: int) -> None:
    lst = lists_repo.get_list(db, list_id)
    if not matches(visibility_spec(real_user), lst):
        raise NotFound(lists_repo.COLLECTION, list_id)
    decision = can_delete(real_user, lst)
    if not decision.allowed:
        raise ApiError(decision.error_code or ErrorCode.PERMISSION_DENIED, decision.reason, status_code=403)
    lists_repo.delete_list(db, list_id, expected_version)


__all__ = [
    "can_delete",
    "create_list",
    "delete_list",
    "get_list_detail",
    "list_lists",
    "replace_list",
]

"""RBAC & Scope Validation Rules for PANIC (Global, Team, Personal/Individual)."""

from __future__ import annotations

from panic_common.models import CatalogItem, EndpointList, PermissionFlag, ScopeType, UserAccount


def has_permission(user: UserAccount, flag: PermissionFlag) -> bool:
    """Return True if the user holds ``flag`` or ``GLOBAL_ADMIN``."""
    perms = set(user.permissions)
    if PermissionFlag.GLOBAL_ADMIN in perms:
        return True
    return flag in perms


def can_use_view_as(user: UserAccount) -> bool:
    """Return True if the user has Admin ('GLOBAL_ADMIN') permissions to use 'View As'."""
    return has_permission(user, PermissionFlag.GLOBAL_ADMIN)


def can_create_or_edit_scope(user: UserAccount, scope: ScopeType) -> tuple[bool, str]:
    """Check whether ``user`` has in-app RBAC permission to create/modify objects of ``scope``."""
    if scope == ScopeType.PERSONAL:
        return True, "Allowed (Personal scope)"
    if scope == ScopeType.GLOBAL:
        if has_permission(user, PermissionFlag.CAN_ADD_GLOBAL):
            return True, "Allowed (Can Add to Global Scope Items)"
        return False, "RBAC Denied: Requires 'Global Admin' or 'Can Add to Global Scope Items' permission."
    if scope == ScopeType.TEAM:
        if has_permission(user, PermissionFlag.CAN_ADD_TEAM):
            return True, "Allowed (Can Add Team Scope Items)"
        return False, "RBAC Denied: Requires 'Global Admin' or 'Can Add Team Scope Items' permission."
    return False, "Unknown scope"


def is_visible_in_scope(
    user: UserAccount,
    scope: ScopeType,
    team_ids: list[str],
    owner_usernames: list[str],
) -> bool:
    """Return True if an object with ``(scope, team_ids, owner_usernames)`` is visible to ``user``."""
    if scope == ScopeType.GLOBAL:
        return True
    if scope == ScopeType.TEAM:
        if has_permission(user, PermissionFlag.GLOBAL_ADMIN):
            return True
        if not team_ids:
            return True
        return bool(set(user.team_ids) & set(team_ids))
    if scope == ScopeType.PERSONAL:
        if not owner_usernames:
            return True
        return user.username in owner_usernames
    return True


def validate_list_item_scopes(
    target_scope: ScopeType,
    item_ids: list[str],
    catalog: list[CatalogItem],
) -> tuple[bool, list[str]]:
    """Enforce that a List only contains CatalogItems with the exact same scope (Global/Team/Personal)."""
    by_id = {c.id: c for c in catalog}
    errors: list[str] = []
    for iid in item_ids:
        item = by_id.get(iid)
        if item is None:
            errors.append(f"Catalog item {iid!r} does not exist.")
            continue
        if item.scope != target_scope:
            errors.append(
                f"Item '{item.title}' has scope {item.scope.value}, "
                f"which cannot be added to a {target_scope.value} list."
            )
    return len(errors) == 0, errors


def filter_items_for_list(target_list: EndpointList, catalog: list[CatalogItem]) -> list[CatalogItem]:
    """Return the resolved CatalogItem objects in ``target_list`` that match its scope."""
    by_id = {c.id: c for c in catalog}
    resolved: list[CatalogItem] = []
    for iid in target_list.item_ids:
        item = by_id.get(iid)
        if item is not None and item.scope == target_list.scope:
            resolved.append(item)
    return resolved

"""Pure visibility filter spec, edit rights and orphan rules (DATA_MODEL §5, §5.1, §6)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from panic_common.errors import ErrorCode
from panic_common.models import PermissionFlag, ScopeType, UserAccount
from panic_common.rbac import has_permission

#: The built-in Default zone (ADR-0001 decision 12). Always exists, never deleted.
DEFAULT_ZONE_ID = "zone-default"
DEFAULT_ZONE_NAME = "Default"


@dataclass(frozen=True)
class VisibilitySpec:
    """What a user can see, independent of any particular resource (DATA_MODEL §5)."""

    username: str
    team_ids: tuple[str, ...]
    all_teams: bool = False


@runtime_checkable
class Scoped(Protocol):
    """Structural shape shared by catalog items, lists and dashboards.

    Declared as read-only properties (not plain attributes): a protocol's plain attributes are
    implicitly read-write, which mypy checks *invariantly* -- a concrete model's ``list[str]``
    field would then fail to satisfy this protocol's ``Sequence[str]``. A read-only property is
    checked covariantly instead, which is all ``matches``/``can_edit`` actually need (they only
    ever read these fields) and what every caller's pydantic model (``CatalogItem``,
    ``EndpointList``, ``Dashboard``) already structurally provides.
    """

    @property
    def scope(self) -> ScopeType: ...
    @property
    def team_ids(self) -> Sequence[str]: ...
    @property
    def owner_usernames(self) -> Sequence[str]: ...
    @property
    def orphaned(self) -> bool: ...


@dataclass(frozen=True)
class Decision:
    """Result of an edit/create rights check (DATA_MODEL §6)."""

    allowed: bool
    error_code: ErrorCode | None = None
    reason: str = ""


def visibility_spec(user: UserAccount) -> VisibilitySpec:
    """Build the pure visibility spec for ``user`` (Global Admins see every TEAM resource)."""
    return VisibilitySpec(
        username=user.username,
        team_ids=tuple(user.team_ids),
        all_teams=PermissionFlag.GLOBAL_ADMIN in user.permissions,
    )


def matches(spec: VisibilitySpec, resource: Scoped) -> bool:
    """Return True if ``resource`` is visible under ``spec``.

    Mirrors the repository's ``$or`` filter exactly (DATA_MODEL §5) so that an in-memory
    and a Mongo-backed check can be run against the same documents and compared.
    """
    if resource.orphaned:
        return spec.all_teams
    if resource.scope == ScopeType.GLOBAL:
        return True
    if resource.scope == ScopeType.TEAM:
        if spec.all_teams:
            return True
        return bool(set(spec.team_ids) & set(resource.team_ids))
    if resource.scope == ScopeType.PERSONAL:
        return spec.username in resource.owner_usernames
    return False


def is_orphan(resource: Scoped, enabled_usernames: Collection[str]) -> bool:
    """Return True if ``resource`` meets the orphan definition (DATA_MODEL §5.1).

    A TEAM resource with no teams, or a PERSONAL resource none of whose owners are
    currently enabled.
    """
    if resource.scope == ScopeType.TEAM:
        return not resource.team_ids
    if resource.scope == ScopeType.PERSONAL:
        if not resource.owner_usernames:
            return True
        return not any(owner in enabled_usernames for owner in resource.owner_usernames)
    return False


@dataclass(frozen=True)
class OrphanAssignment:
    """The field changes for converting an orphan to a PERSONAL resource of ``username``."""

    scope: ScopeType
    team_ids: tuple[str, ...]
    owner_usernames: tuple[str, ...]
    orphaned: bool
    kept_item_ids: tuple[str, ...] | None = None
    dropped_item_ids: tuple[str, ...] | None = None


def assign_orphan_to_user(
    username: str,
    *,
    item_ids: Collection[str] | None = None,
    personal_item_ids_for_user: Collection[str] | None = None,
) -> OrphanAssignment:
    """Compute the field changes for the "assign to user" orphan action (DATA_MODEL §5.1).

    When ``item_ids`` (an orphaned list's items) is given, only those ids that are also in
    ``personal_item_ids_for_user`` (that user's own PERSONAL catalog items) are kept; the
    rest are dropped and reported.
    """
    kept: tuple[str, ...] | None = None
    dropped: tuple[str, ...] | None = None
    if item_ids is not None:
        keepable = set(personal_item_ids_for_user or ())
        kept_list = [iid for iid in item_ids if iid in keepable]
        dropped_list = [iid for iid in item_ids if iid not in keepable]
        kept, dropped = tuple(kept_list), tuple(dropped_list)
    return OrphanAssignment(
        scope=ScopeType.PERSONAL,
        team_ids=(),
        owner_usernames=(username,),
        orphaned=False,
        kept_item_ids=kept,
        dropped_item_ids=dropped,
    )


def can_create(user: UserAccount, scope: ScopeType, team_ids: Collection[str] = ()) -> Decision:
    """May ``user`` create a resource with ``scope`` (and, for TEAM, these ``team_ids``)?"""
    if scope == ScopeType.PERSONAL:
        return Decision(allowed=True)
    if scope == ScopeType.GLOBAL:
        if has_permission(user, PermissionFlag.CAN_ADD_GLOBAL):
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.PERMISSION_DENIED,
            reason="Requires Global Admin or Can Add Global Scope Items.",
        )
    if scope == ScopeType.TEAM:
        if not has_permission(user, PermissionFlag.CAN_ADD_TEAM):
            return Decision(
                allowed=False,
                error_code=ErrorCode.PERMISSION_DENIED,
                reason="Requires Global Admin or Can Add Team Scope Items.",
            )
        if PermissionFlag.GLOBAL_ADMIN in user.permissions:
            return Decision(allowed=True)
        if team_ids and set(team_ids).issubset(user.team_ids):
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.PERMISSION_DENIED,
            reason="Must be a member of every chosen team.",
        )
    return Decision(allowed=False, error_code=ErrorCode.PERMISSION_DENIED, reason="Unknown scope.")


def can_edit(user: UserAccount, resource: Scoped) -> Decision:
    """May ``user`` edit or delete ``resource``? Call only on an already-visible resource —

    an invisible resource is reported as ``404 NOT_FOUND``, never via this function.
    """
    if resource.orphaned:
        return Decision(
            allowed=False,
            error_code=ErrorCode.ORPHANED_RESOURCE,
            reason="Orphaned resources are read-only; assign to a user or delete instead.",
        )
    if resource.scope == ScopeType.GLOBAL:
        if has_permission(user, PermissionFlag.CAN_ADD_GLOBAL):
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.PERMISSION_DENIED,
            reason="Requires Global Admin or Can Add Global Scope Items.",
        )
    if resource.scope == ScopeType.TEAM:
        if not has_permission(user, PermissionFlag.CAN_ADD_TEAM):
            return Decision(
                allowed=False,
                error_code=ErrorCode.PERMISSION_DENIED,
                reason="Requires Global Admin or Can Add Team Scope Items.",
            )
        if PermissionFlag.GLOBAL_ADMIN in user.permissions:
            return Decision(allowed=True)
        if set(user.team_ids) & set(resource.team_ids):
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.PERMISSION_DENIED,
            reason="Must be a member of at least one of the resource's teams.",
        )
    if resource.scope == ScopeType.PERSONAL:
        # Owner decision: Global Admins cannot edit or delete other users' PERSONAL resources.
        if user.username in resource.owner_usernames:
            return Decision(allowed=True)
        return Decision(
            allowed=False,
            error_code=ErrorCode.PERMISSION_DENIED,
            reason="Only an owner may edit a Personal resource.",
        )
    return Decision(allowed=False, error_code=ErrorCode.PERMISSION_DENIED, reason="Unknown scope.")

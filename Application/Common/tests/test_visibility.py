"""Property-style tests for panic_common.visibility: scoped access, edit rights, orphans."""

from __future__ import annotations

import itertools

from panic_common.errors import ErrorCode
from panic_common.models import PermissionFlag, ScopeType, UserAccount
from panic_common.visibility import (
    DEFAULT_ZONE_ID,
    Decision,
    Scoped,
    assign_orphan_to_user,
    can_create,
    can_edit,
    is_orphan,
    matches,
    visibility_spec,
)


class _Resource:
    def __init__(
        self,
        scope: ScopeType,
        team_ids: tuple[str, ...] = (),
        owner_usernames: tuple[str, ...] = (),
        orphaned: bool = False,
    ) -> None:
        self.scope = scope
        self.team_ids = team_ids
        self.owner_usernames = owner_usernames
        self.orphaned = orphaned


def _user(username: str, permissions: tuple[PermissionFlag, ...] = (), team_ids: tuple[str, ...] = ()) -> UserAccount:
    return UserAccount(
        id=f"usr-{username}",
        username=username,
        display_name=username.title(),
        default_remote_user=username,
        permissions=list(permissions),
        team_ids=list(team_ids),
    )


USERNAMES = ("alex", "priya", "jordan")
TEAM_SETS = ((), ("team-a",), ("team-a", "team-b"), ("team-c",))
PERMISSION_SETS = (
    (),
    (PermissionFlag.CAN_ADD_TEAM,),
    (PermissionFlag.CAN_ADD_GLOBAL,),
    (PermissionFlag.GLOBAL_ADMIN,),
)


def test_scoped_satisfies_protocol() -> None:
    assert isinstance(_Resource(ScopeType.GLOBAL), Scoped)


def test_global_is_always_visible_and_never_orphaned() -> None:
    for username, perms, teams in itertools.product(USERNAMES, PERMISSION_SETS, TEAM_SETS):
        user = _user(username, perms, teams)
        spec = visibility_spec(user)
        resource = _Resource(ScopeType.GLOBAL)
        assert matches(spec, resource) is True
        assert is_orphan(resource, enabled_usernames={username}) is False


def test_team_visibility_requires_membership_unless_global_admin() -> None:
    member = _user("priya", team_ids=("team-a",))
    outsider = _user("alex", team_ids=("team-b",))
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))
    resource = _Resource(ScopeType.TEAM, team_ids=("team-a",))

    assert matches(visibility_spec(member), resource) is True
    assert matches(visibility_spec(outsider), resource) is False
    assert matches(visibility_spec(admin), resource) is True


def test_personal_visibility_is_owner_only_including_for_admins() -> None:
    owner = _user("alex")
    other = _user("priya")
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))
    resource = _Resource(ScopeType.PERSONAL, owner_usernames=("alex",))

    assert matches(visibility_spec(owner), resource) is True
    assert matches(visibility_spec(other), resource) is False
    # F4: a Global Admin can see it (admins see everything not orphaned... but PERSONAL
    # visibility is owner-only even for admins, matching the Mongo $or exactly).
    assert matches(visibility_spec(admin), resource) is False


def test_f4_cannot_edit_another_users_personal_item_plain_or_admin() -> None:
    owner = _user("alex")
    other = _user("priya")
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))
    resource = _Resource(ScopeType.PERSONAL, owner_usernames=("alex",))

    assert can_edit(owner, resource).allowed is True
    other_decision = can_edit(other, resource)
    assert other_decision.allowed is False
    assert other_decision.error_code == ErrorCode.PERMISSION_DENIED
    admin_decision = can_edit(admin, resource)
    assert admin_decision.allowed is False
    assert admin_decision.error_code == ErrorCode.PERMISSION_DENIED


def test_f4_cannot_edit_team_item_for_a_team_you_are_not_in() -> None:
    outsider = _user("alex", permissions=(PermissionFlag.CAN_ADD_TEAM,), team_ids=("team-z",))
    resource = _Resource(ScopeType.TEAM, team_ids=("team-a",))
    decision = can_edit(outsider, resource)
    assert decision.allowed is False
    assert decision.error_code == ErrorCode.PERMISSION_DENIED


def test_team_member_with_can_add_team_may_edit() -> None:
    member = _user("priya", permissions=(PermissionFlag.CAN_ADD_TEAM,), team_ids=("team-a",))
    resource = _Resource(ScopeType.TEAM, team_ids=("team-a", "team-b"))
    assert can_edit(member, resource).allowed is True


def test_global_admin_may_edit_any_team_resource() -> None:
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))
    resource = _Resource(ScopeType.TEAM, team_ids=("team-a",))
    assert can_edit(admin, resource).allowed is True


def test_orphan_team_resource_invisible_to_non_admins_and_read_only_for_admins() -> None:
    member = _user("priya", team_ids=())
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))
    orphan = _Resource(ScopeType.TEAM, team_ids=(), orphaned=True)

    assert matches(visibility_spec(member), orphan) is False
    assert matches(visibility_spec(admin), orphan) is True

    admin_decision = can_edit(admin, orphan)
    assert admin_decision.allowed is False
    assert admin_decision.error_code == ErrorCode.ORPHANED_RESOURCE


def test_orphan_personal_resource_invisible_to_non_admins_and_read_only_for_admins() -> None:
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))
    other = _user("alex")
    orphan = _Resource(ScopeType.PERSONAL, owner_usernames=(), orphaned=True)

    assert matches(visibility_spec(other), orphan) is False
    assert matches(visibility_spec(admin), orphan) is True
    assert can_edit(admin, orphan).allowed is False


def test_is_orphan_team_with_no_teams() -> None:
    assert is_orphan(_Resource(ScopeType.TEAM, team_ids=()), enabled_usernames=set()) is True
    assert is_orphan(_Resource(ScopeType.TEAM, team_ids=("team-a",)), enabled_usernames=set()) is False


def test_is_orphan_personal_with_no_enabled_owner() -> None:
    assert is_orphan(_Resource(ScopeType.PERSONAL, owner_usernames=()), enabled_usernames={"alex"}) is True
    assert (
        is_orphan(_Resource(ScopeType.PERSONAL, owner_usernames=("alex",)), enabled_usernames=set())
        is True
    )
    assert (
        is_orphan(_Resource(ScopeType.PERSONAL, owner_usernames=("alex",)), enabled_usernames={"alex"})
        is False
    )
    # At least one enabled owner is enough.
    assert (
        is_orphan(
            _Resource(ScopeType.PERSONAL, owner_usernames=("alex", "priya")),
            enabled_usernames={"priya"},
        )
        is False
    )


def test_assign_orphan_to_user_sets_personal_fields() -> None:
    result = assign_orphan_to_user("alex")
    assert result.scope == ScopeType.PERSONAL
    assert result.owner_usernames == ("alex",)
    assert result.team_ids == ()
    assert result.orphaned is False


def test_assign_orphan_to_user_filters_list_items_to_the_users_personal_items() -> None:
    result = assign_orphan_to_user(
        "alex",
        item_ids=["c-1", "c-2", "c-3"],
        personal_item_ids_for_user=["c-1", "c-3"],
    )
    assert result.kept_item_ids == ("c-1", "c-3")
    assert result.dropped_item_ids == ("c-2",)


def test_can_create_personal_always_allowed() -> None:
    for username, perms in itertools.product(USERNAMES, PERMISSION_SETS):
        assert can_create(_user(username, perms), ScopeType.PERSONAL).allowed is True


def test_can_create_global_requires_permission() -> None:
    plain = _user("alex")
    privileged = _user("priya", permissions=(PermissionFlag.CAN_ADD_GLOBAL,))
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))
    assert can_create(plain, ScopeType.GLOBAL).allowed is False
    assert can_create(privileged, ScopeType.GLOBAL).allowed is True
    assert can_create(admin, ScopeType.GLOBAL).allowed is True


def test_can_create_team_requires_membership_in_every_chosen_team() -> None:
    member = _user("priya", permissions=(PermissionFlag.CAN_ADD_TEAM,), team_ids=("team-a", "team-b"))
    partial_member = _user("alex", permissions=(PermissionFlag.CAN_ADD_TEAM,), team_ids=("team-a",))
    admin = _user("jordan", permissions=(PermissionFlag.GLOBAL_ADMIN,))

    assert can_create(member, ScopeType.TEAM, team_ids=("team-a", "team-b")).allowed is True
    assert can_create(partial_member, ScopeType.TEAM, team_ids=("team-a", "team-b")).allowed is False
    assert can_create(admin, ScopeType.TEAM, team_ids=("team-a", "team-b")).allowed is True


def test_default_zone_id_constant() -> None:
    assert DEFAULT_ZONE_ID == "zone-default"


def test_decision_is_frozen_dataclass_shape() -> None:
    decision = Decision(allowed=True)
    assert decision.allowed is True
    assert decision.error_code is None

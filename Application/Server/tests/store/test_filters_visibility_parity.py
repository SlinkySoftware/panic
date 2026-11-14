"""Acceptance: ``panic_server.store.filters.visibility_filter`` and
``panic_common.rbac.is_visible_in_scope`` must agree on every generated document (DATA_MODEL.md §5).

~2,000 synthetic documents are generated across GLOBAL/TEAM/PERSONAL, including TEAM docs with no
``team_ids`` and PERSONAL docs with no enabled owner (the orphan cases), with ``orphaned`` set
consistently via ``panic_common.visibility.is_orphan``. For a handful of representative users, the
set of ids the real Mongo filter matches must equal the set of ids ``is_visible_in_scope`` (AND the
orphan rule) says should be visible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pytest
from pymongo.database import Database

from panic_common.models import PermissionFlag, UserAccount
from panic_common.rbac import is_visible_in_scope
from panic_common.visibility import VisibilitySpec, is_orphan
from panic_server.store.filters import visibility_filter

pytestmark = [pytest.mark.mongo]

FIXTURE_COLLECTION = "_visibility_fixture"
N_DOCS = 2000

TEAMS = [f"team-{i}" for i in range(6)]
OWNER_POOL = [f"user{i}" for i in range(24)]
# A third of the pool is "disabled" (never an enabled owner); used to build genuine PERSONAL orphans.
DISABLED_USERNAMES = set(OWNER_POOL[::3])
ENABLED_USERNAMES = (set(OWNER_POOL) - DISABLED_USERNAMES) | {"alice", "bob", "carol"}


@dataclass(frozen=True)
class _Scoped:
    scope: str
    team_ids: list[str]
    owner_usernames: list[str]


def _make_user(username: str, *, team_ids: tuple[str, ...], admin: bool) -> UserAccount:
    return UserAccount(
        id=f"usr-{username}",
        username=username,
        display_name=username.title(),
        default_remote_user=username,
        permissions=[PermissionFlag.GLOBAL_ADMIN] if admin else [],
        team_ids=list(team_ids),
    )


ALICE = _make_user("alice", team_ids=("team-0", "team-1"), admin=False)
BOB = _make_user("bob", team_ids=(), admin=False)
CAROL = _make_user("carol", team_ids=(), admin=True)

USERS = [ALICE, BOB, CAROL]


def _spec_for(user: UserAccount) -> VisibilitySpec:
    return VisibilitySpec(
        username=user.username,
        team_ids=tuple(user.team_ids),
        all_teams=PermissionFlag.GLOBAL_ADMIN in user.permissions,
    )


def _generate_docs(rng: random.Random) -> list[dict]:
    docs = []
    for i in range(N_DOCS):
        roll = rng.random()
        if roll < 0.34:
            scope = "GLOBAL"
            team_ids: list[str] = []
            owner_usernames: list[str] = []
        elif roll < 0.67:
            scope = "TEAM"
            owner_usernames = []
            # A 12% chance of the deliberate TEAM-with-no-teams orphan case.
            team_ids = [] if rng.random() < 0.12 else rng.sample(TEAMS, k=rng.randint(1, 3))
        else:
            scope = "PERSONAL"
            team_ids = []
            if rng.random() < 0.15:
                # Deliberate orphan case: no owner at all. (A PERSONAL doc whose owners are all
                # disabled but the list is non-empty is also an orphan per is_orphan(), but
                # panic_common.rbac.is_visible_in_scope -- the pre-Stage-6 function this test
                # holds the Mongo filter to -- has no admin-sees-all-orphans bypass for a
                # non-empty PERSONAL owner_usernames list, only for TEAM and for "no owner at
                # all"; that sub-case is covered directly in tests/store/test_repos_orphans.py
                # instead of here, to keep this parity check unambiguous.)
                owner_usernames = []
            else:
                enabled_pool = [u for u in OWNER_POOL if u in ENABLED_USERNAMES]
                owner_usernames = rng.sample(enabled_pool, k=rng.randint(1, 2))
        fixture = _Scoped(scope=scope, team_ids=team_ids, owner_usernames=owner_usernames)
        orphaned = is_orphan(fixture, ENABLED_USERNAMES)
        docs.append(
            {
                "_id": f"fixture-{i}",
                "scope": scope,
                "team_ids": team_ids,
                "owner_usernames": owner_usernames,
                "orphaned": orphaned,
            }
        )
    return docs


@pytest.fixture(scope="module")
def fixture_docs(mongo_db: Database) -> list[dict]:
    rng = random.Random(1234567)
    docs = _generate_docs(rng)
    coll = mongo_db[FIXTURE_COLLECTION]
    coll.delete_many({})
    coll.insert_many(docs)
    return docs


@pytest.mark.parametrize("user", USERS, ids=[u.username for u in USERS])
def test_visibility_filter_matches_is_visible_in_scope(
    mongo_db: Database, fixture_docs: list[dict], user: UserAccount
) -> None:
    spec = _spec_for(user)

    expected_ids = set()
    for doc in fixture_docs:
        visible = is_visible_in_scope(user, doc["scope"], doc["team_ids"], doc["owner_usernames"])
        orphan_ok = (not doc["orphaned"]) or (spec.all_teams and doc["orphaned"])
        if visible and orphan_ok:
            expected_ids.add(doc["_id"])

    mongo_ids = {d["_id"] for d in mongo_db[FIXTURE_COLLECTION].find(visibility_filter(spec), {"_id": 1})}

    assert mongo_ids == expected_ids

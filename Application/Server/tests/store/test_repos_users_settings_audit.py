"""``store.repos.users`` / ``settings`` / ``audit`` (DATA_MODEL.md §4.1, §4.8, §4.9)."""

from __future__ import annotations

import time

import pytest
from pymongo.database import Database

from panic_server.store.errors import DuplicateKey, NotFound
from panic_server.store.repos import audit, settings, users

pytestmark = [pytest.mark.mongo]


def test_user_crud_prefs_roundtrip_and_password_hash_never_leaks(mongo_db: Database) -> None:
    user = users.create_user(
        mongo_db,
        username="jdoe",
        display_name="J. Doe",
        default_remote_user="jdoe",
        password_hash="pbkdf2_sha256$fakehash",
    )
    assert user.density == "COMFORT"
    assert user.theme == "DARK"
    assert not hasattr(user, "password_hash")
    assert "password_hash" not in user.model_dump()

    stored_hash = users.get_password_hash(mongo_db, "jdoe")
    assert stored_hash == "pbkdf2_sha256$fakehash"

    updated = users.update_user(mongo_db, user.id, user.version, density="COMPACT", theme="LIGHT")
    assert updated.density == "COMPACT"
    assert updated.theme == "LIGHT"
    raw = mongo_db["users"].find_one({"_id": user.id})
    assert raw is not None
    assert raw["prefs"]["density"] == "COMPACT"

    with pytest.raises(DuplicateKey):
        users.create_user(mongo_db, username="jdoe", display_name="Dup", default_remote_user="jdoe")

    by_username = users.get_user_by_username(mongo_db, "jdoe")
    assert by_username is not None and by_username.id == user.id


def test_user_queries(mongo_db: Database) -> None:
    users.create_user(
        mongo_db,
        username="admin1",
        display_name="Admin One",
        default_remote_user="admin1",
        permissions=["GLOBAL_ADMIN"],
    )
    users.create_user(mongo_db, username="teamuser1", display_name="T", default_remote_user="t", team_ids=["team-x"])

    admins = users.list_users(mongo_db, permission="GLOBAL_ADMIN")
    assert any(u.username == "admin1" for u in admins)
    assert users.count_enabled_admins(mongo_db) >= 1

    team_members = users.list_users(mongo_db, team_id="team-x")
    assert any(u.username == "teamuser1" for u in team_members)


def test_system_settings_ensure_is_idempotent_and_cas_update(mongo_db: Database) -> None:
    first = settings.ensure_system_settings(mongo_db, default_global_dashboard_id="", updated_by="system")
    second = settings.ensure_system_settings(mongo_db, default_global_dashboard_id="other", updated_by="system")
    assert first.version == second.version == 1
    assert second.default_global_dashboard_id == ""  # ensure_* never overwrites an existing doc

    updated = settings.set_default_global_dashboard(
        mongo_db, first.version, default_global_dashboard_id="dash-1", updated_by="jdoe"
    )
    assert updated.default_global_dashboard_id == "dash-1"
    assert updated.updated_by == "jdoe"
    assert updated.version == 2

    fetched = settings.get_system_settings(mongo_db)
    assert fetched is not None
    assert fetched.default_global_dashboard_id == "dash-1"


def test_audit_append_and_keyset_pagination(mongo_db: Database) -> None:
    for i in range(5):
        audit.append_audit(
            mongo_db,
            actor_username="jdoe",
            action="catalog.create",
            target_type="catalog_item",
            target_id=f"item-{i}",
            summary=f"created item {i}",
            client_ip="10.0.0.1",
        )
        time.sleep(0.001)

    page1 = audit.list_audit(mongo_db, actor_username="jdoe", limit=2)
    assert len(page1) == 2
    last = page1[-1]
    page2 = audit.list_audit(mongo_db, actor_username="jdoe", limit=2, before=(last.created_at, last.id))
    assert len(page2) == 2
    assert {e.id for e in page1}.isdisjoint({e.id for e in page2})
    # Newest first.
    assert page1[0].created_at >= page1[1].created_at >= page2[0].created_at

    entry = audit.list_audit(mongo_db, action="catalog.create", limit=1)[0]
    assert entry.action == "catalog.create"
    assert not hasattr(entry, "client_ip")  # not on panic_common.models.AuditLogEntry


def test_not_found_on_missing_user(mongo_db: Database) -> None:
    with pytest.raises(NotFound):
        users.get_user(mongo_db, "no-such-user")

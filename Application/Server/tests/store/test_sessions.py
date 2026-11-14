"""``panic_server.store.sessions.SessionStore`` (DATA_MODEL.md §4.11, AR-4.7).

Acceptance: a session created through one client/process is used by a second process
immediately, and still works after the first process "restarts" (``reset_client()``).
"""

from __future__ import annotations

import pytest
from pymongo.database import Database

from panic_server.store.client import reset_client
from panic_server.store.sessions import SessionStore, delete_sessions_for_user

pytestmark = [pytest.mark.mongo]


def _store(db_name: str) -> SessionStore:
    s = SessionStore()
    s.db_name = db_name  # type: ignore[attr-defined]
    return s


def test_session_created_on_one_store_is_read_by_another_immediately(mongo_db: Database) -> None:
    process_a = _store(mongo_db.name)
    process_a["panic_user_id"] = "usr-alice"
    process_a.save()
    key = process_a.session_key
    assert key is not None

    # A second "process" (separate SessionStore instance) sees it right away.
    process_b = _store(mongo_db.name)
    process_b._session_key = key  # simulate reading the session cookie
    assert process_b.exists(key)
    data = process_b.load()
    assert data["panic_user_id"] == "usr-alice"

    raw = mongo_db["sessions"].find_one({"_id": key})
    assert raw is not None
    assert raw["uid"] == "usr-alice"


def test_session_survives_simulated_process_restart(mongo_db: Database) -> None:
    process_a = _store(mongo_db.name)
    process_a["panic_user_id"] = "usr-bob"
    process_a.save()
    key = process_a.session_key
    assert key is not None

    # Simulate the first process (or its load-balanced replica) restarting: drop its lazy
    # per-process MongoClient and reconnect with a fresh SessionStore.
    reset_client()
    process_a_restarted = _store(mongo_db.name)
    process_a_restarted._session_key = key
    data = process_a_restarted.load()
    assert data["panic_user_id"] == "usr-bob"


def test_session_update_and_delete(mongo_db: Database) -> None:
    store = _store(mongo_db.name)
    store["panic_user_id"] = "usr-carol"
    store.save()
    key = store.session_key
    assert key is not None

    store["extra"] = "value"
    store.save()
    reread = _store(mongo_db.name)
    reread._session_key = key
    assert reread.load()["extra"] == "value"

    store.delete()
    assert not _store(mongo_db.name).exists(key)


def test_delete_sessions_for_user(mongo_db: Database) -> None:
    s1 = _store(mongo_db.name)
    s1["panic_user_id"] = "usr-to-disable"
    s1.save()
    s2 = _store(mongo_db.name)
    s2["panic_user_id"] = "usr-to-disable"
    s2.save()
    other = _store(mongo_db.name)
    other["panic_user_id"] = "usr-someone-else"
    other.save()

    deleted = delete_sessions_for_user("usr-to-disable", db_name=mongo_db.name)
    assert deleted == 2
    assert _store(mongo_db.name).exists(other.session_key) is True

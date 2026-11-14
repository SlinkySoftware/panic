"""``panic_server.store.client`` (DATA_MODEL.md §2)."""

from __future__ import annotations

import pytest
from pymongo.database import Database
from pymongo.errors import ServerSelectionTimeoutError

from panic_server.store import client as store_client

pytestmark = [pytest.mark.mongo]


def test_get_db_uses_mongo_db_fixture_override(mongo_db: Database) -> None:
    db = store_client.get_db()
    assert db.name == mongo_db.name


def test_get_db_name_override(mongo_db: Database) -> None:
    db = store_client.get_db("some_other_name")
    assert db.name == "some_other_name"


def test_ping_ok(mongo_db: Database) -> None:
    ok, err = store_client.ping()
    assert ok is True
    assert err is None


def test_reset_client_forces_new_client(mongo_db: Database) -> None:
    first = store_client.get_client()
    store_client.reset_client()
    second = store_client.get_client()
    assert first is not second
    # Still works after "restart".
    ok, _ = store_client.ping()
    assert ok is True


def test_is_transient_detects_server_selection_timeout() -> None:
    exc = ServerSelectionTimeoutError("no servers")
    assert store_client.is_transient(exc) is True


def test_is_transient_false_for_unrelated_error() -> None:
    assert store_client.is_transient(ValueError("boom")) is False


def test_is_transient_walks_cause_chain() -> None:
    outer: RuntimeError | None = None
    try:
        try:
            raise ServerSelectionTimeoutError("root cause")
        except ServerSelectionTimeoutError as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as caught:
        outer = caught
    assert outer is not None
    assert store_client.is_transient(outer) is True

"""Server test configuration: every test runs against a fresh, seeded relational database."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from django.conf import settings
from django.core.cache import cache
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from panic_server.conf import env
from panic_server.state import STORE

MONGO_PROBE_TIMEOUT_MS = 2000


@pytest.fixture(autouse=True)
def _db_backed_store(db: None) -> None:
    cache.clear()  # rate-limit counters
    STORE.simulation.active_user_id = "usr-admin"
    STORE.simulation.view_as_user_id = None
    STORE.reset()


def _base_test_mongo_uri() -> str:
    """``PANIC_TEST_MONGO_URI``, else ``PANIC_MONGO_URI``, else the local dev-mongo container."""
    return env("PANIC_TEST_MONGO_URI") or env("PANIC_MONGO_URI") or "mongodb://127.0.0.1:27117/"


@pytest.fixture(scope="session")
def mongo_db() -> Iterator[Database]:  # type: ignore[type-arg]
    """A uniquely-named test database on a real MongoDB, dropped at session teardown.

    Also points ``settings.PANIC_MONGO_URI`` (and so ``panic_server.store.client.get_db()``)
    at this same database for the rest of the session, so repo code under test needs no special
    wiring. Skips the whole session (with a clear reason) if Mongo is unreachable.
    """
    base_uri = _base_test_mongo_uri()
    try:
        client: MongoClient = MongoClient(base_uri, serverSelectionTimeoutMS=MONGO_PROBE_TIMEOUT_MS)  # type: ignore[type-arg]
        client.admin.command("ping")
    except PyMongoError as e:
        pytest.skip(f"no reachable MongoDB at {base_uri!r}: {type(e).__name__}: {e}")
        return

    db_name = f"panic_test_{uuid.uuid4().hex[:8]}"
    parts = urlsplit(base_uri)
    test_uri = urlunsplit((parts.scheme, parts.netloc, f"/{db_name}", parts.query, parts.fragment))

    original_uri = settings.PANIC_MONGO_URI
    settings.PANIC_MONGO_URI = test_uri
    try:
        yield client[db_name]
    finally:
        from panic_server.store.client import reset_client

        reset_client()
        settings.PANIC_MONGO_URI = original_uri
        client.drop_database(db_name)
        client.close()

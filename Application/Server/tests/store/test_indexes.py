"""``panic_server.store.indexes`` (DATA_MODEL.md §4): idempotency and conflict detection."""

from __future__ import annotations

import pytest
from django.test import override_settings
from pymongo.database import Database

from panic_server.store.indexes import AUDIT_TTL_INDEX_NAME, INDEXES, ensure_indexes

pytestmark = [pytest.mark.mongo]


def test_ensure_indexes_creates_everything(mongo_db: Database) -> None:
    # The session-scoped autouse fixture in tests/store/conftest.py may already have run this,
    # so "created" + "existing" together (not "created" alone) is what's guaranteed fresh or not.
    report = ensure_indexes(mongo_db)
    expected_names = {f"{spec.collection}.{spec.name}" for spec in INDEXES}
    expected_names.add(f"audit_log.{AUDIT_TTL_INDEX_NAME}")
    assert expected_names <= set(report.created) | set(report.existing)


def test_ensure_indexes_is_idempotent(mongo_db: Database) -> None:
    ensure_indexes(mongo_db)  # whatever this session's db already has, bring it to full.
    report = ensure_indexes(mongo_db)
    assert report.created == []
    assert report.changed == []
    assert report.dropped == []
    expected_names = {f"{spec.collection}.{spec.name}" for spec in INDEXES}
    expected_names.add(f"audit_log.{AUDIT_TTL_INDEX_NAME}")
    assert expected_names <= set(report.existing)


def test_ensure_indexes_detects_conflicting_definition(mongo_db: Database) -> None:
    ensure_indexes(mongo_db)
    # Drop and recreate "users.username_unique" with a different (non-unique) definition.
    mongo_db["users"].drop_index("username_unique")
    mongo_db["users"].create_index([("username", 1)], name="username_unique", unique=False)
    with pytest.raises(RuntimeError, match="username_unique"):
        ensure_indexes(mongo_db)
    # Repair it so later tests in this session aren't poisoned.
    mongo_db["users"].drop_index("username_unique")
    mongo_db["users"].create_index([("username", 1)], name="username_unique", unique=True)


def test_ensure_indexes_coll_mods_audit_ttl_when_retention_changes(mongo_db: Database) -> None:
    ensure_indexes(mongo_db)
    info = mongo_db["audit_log"].index_information()
    assert info[AUDIT_TTL_INDEX_NAME]["expireAfterSeconds"] == 365 * 86400

    with override_settings(PANIC_AUDIT_RETENTION_DAYS=30):
        report = ensure_indexes(mongo_db)
    assert f"audit_log.{AUDIT_TTL_INDEX_NAME}" in report.changed
    info = mongo_db["audit_log"].index_information()
    assert info[AUDIT_TTL_INDEX_NAME]["expireAfterSeconds"] == 30 * 86400

    # Restore the default for other tests sharing this session database.
    ensure_indexes(mongo_db)
    info = mongo_db["audit_log"].index_information()
    assert info[AUDIT_TTL_INDEX_NAME]["expireAfterSeconds"] == 365 * 86400


def test_ensure_indexes_drops_audit_ttl_when_retention_disabled(mongo_db: Database) -> None:
    ensure_indexes(mongo_db)
    assert AUDIT_TTL_INDEX_NAME in mongo_db["audit_log"].index_information()

    with override_settings(PANIC_AUDIT_RETENTION_DAYS=0):
        report = ensure_indexes(mongo_db)
    assert f"audit_log.{AUDIT_TTL_INDEX_NAME}" in report.dropped
    assert AUDIT_TTL_INDEX_NAME not in mongo_db["audit_log"].index_information()

    # Restore it.
    ensure_indexes(mongo_db)
    assert AUDIT_TTL_INDEX_NAME in mongo_db["audit_log"].index_information()

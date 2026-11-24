"""``panic_server.store.migrate`` (DATA_MODEL.md §4.13): numbered, idempotent migration steps."""

from __future__ import annotations

import pytest
from pymongo.database import Database

from panic_server.store.migrate import SCHEMA_COLLECTION, SCHEMA_DOC_ID, STEPS, current_schema_version, run_migrations
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]

LATEST = STEPS[-1][0]


def test_step_1_creates_default_zone_and_system_settings_idempotently(mongo_db: Database) -> None:
    # This test shares a session-wide database with other tests/management-command invocations,
    # so step 1 may already be applied; what matters is that it converges and stays idempotent.
    run_migrations(mongo_db)
    assert current_schema_version(mongo_db) == LATEST

    zone = zones_repo.get_zone(mongo_db, zones_repo.DEFAULT_ZONE_ID)
    assert zone.name == zones_repo.DEFAULT_ZONE_NAME
    assert zone.builtin is True

    doc = settings_repo.get_system_settings(mongo_db)
    assert doc is not None

    # Running again is a no-op: nothing new applied, and the documents are untouched.
    second_run = run_migrations(mongo_db)
    assert second_run == []
    assert current_schema_version(mongo_db) == LATEST
    zone_again = zones_repo.get_zone(mongo_db, zones_repo.DEFAULT_ZONE_ID)
    assert zone_again.version == zone.version


def test_step_2_moves_legacy_catalog_items_to_connections(mongo_db: Database) -> None:
    run_migrations(mongo_db)
    mongo_db[catalog_repo.COLLECTION].insert_one(
        {
            "_id": "legacy-web-item",
            "title": "Legacy portal",
            "protocol": "WEB",
            "host": "portal.example.net",
            "port": 8443,
            "path_or_args": "/ui",
            "custom_uri": "",
            "normalized_key": "web://portal.example.net:8443/ui",
            "scope": "GLOBAL",
            "version": 1,
        }
    )
    # Pretend only step 1 had run, so the runner re-applies step 2 (which is idempotent for new-shape docs).
    mongo_db[SCHEMA_COLLECTION].update_one({"_id": SCHEMA_DOC_ID}, {"$set": {"version": 1}})
    applied = run_migrations(mongo_db)
    assert [a.split(":")[0] for a in applied] == [f"step {n}" for n, _ in STEPS if n >= 2]
    assert current_schema_version(mongo_db) == LATEST

    doc = mongo_db[catalog_repo.COLLECTION].find_one({"_id": "legacy-web-item"})
    assert doc is not None
    assert doc["connections"] == [{"protocol": "URL", "port": 8443, "path_or_args": "/ui", "custom_uri": ""}]
    assert doc["normalized_keys"] == ["url://portal.example.net:8443/ui"]
    assert not set(catalog_repo.LEGACY_FIELDS) & set(doc)
    assert catalog_repo.get_catalog_item(mongo_db, "legacy-web-item").primary.protocol == "URL"

    # Idempotent: re-running the step leaves the converted doc alone.
    mongo_db[SCHEMA_COLLECTION].update_one({"_id": SCHEMA_DOC_ID}, {"$set": {"version": 1}})
    run_migrations(mongo_db)
    assert mongo_db[catalog_repo.COLLECTION].find_one({"_id": "legacy-web-item"}) == doc
    mongo_db[catalog_repo.COLLECTION].delete_one({"_id": "legacy-web-item"})

"""``panic_server.store.migrate`` (DATA_MODEL.md §4.13): numbered, idempotent migration steps."""

from __future__ import annotations

import pytest
from pymongo.database import Database

from panic_server.store.migrate import current_schema_version, run_migrations
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]


def test_step_1_creates_default_zone_and_system_settings_idempotently(mongo_db: Database) -> None:
    # This test shares a session-wide database with other tests/management-command invocations,
    # so step 1 may already be applied; what matters is that it converges and stays idempotent.
    run_migrations(mongo_db)
    assert current_schema_version(mongo_db) == 1

    zone = zones_repo.get_zone(mongo_db, zones_repo.DEFAULT_ZONE_ID)
    assert zone.name == zones_repo.DEFAULT_ZONE_NAME
    assert zone.builtin is True

    doc = settings_repo.get_system_settings(mongo_db)
    assert doc is not None

    # Running again is a no-op: nothing new applied, and the documents are untouched.
    second_run = run_migrations(mongo_db)
    assert second_run == []
    assert current_schema_version(mongo_db) == 1
    zone_again = zones_repo.get_zone(mongo_db, zones_repo.DEFAULT_ZONE_ID)
    assert zone_again.version == zone.version

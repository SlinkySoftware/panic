"""``manage.py panic_ensure_indexes`` / ``panic_migrate`` as actual Django management commands."""

from __future__ import annotations

import io

import pytest
from django.core.management import CommandError, call_command
from pymongo.database import Database

pytestmark = [pytest.mark.mongo]


def test_panic_ensure_indexes_command_is_idempotent_and_reports_conflicts(mongo_db: Database) -> None:
    out = io.StringIO()
    call_command("panic_ensure_indexes", stdout=out)
    assert "indexes:" in out.getvalue()

    out2 = io.StringIO()
    call_command("panic_ensure_indexes", stdout=out2)
    assert "0 created" in out2.getvalue()

    mongo_db["sites"].drop_index("code_unique")
    mongo_db["sites"].create_index([("code", 1)], name="code_unique", unique=False)
    with pytest.raises(CommandError, match="code_unique"):
        call_command("panic_ensure_indexes", stdout=io.StringIO())

    # Repair for any later test sharing this session database.
    mongo_db["sites"].drop_index("code_unique")
    mongo_db["sites"].create_index([("code", 1)], name="code_unique", unique=True)


def test_panic_migrate_command_runs_step_1(mongo_db: Database) -> None:
    out = io.StringIO()
    call_command("panic_migrate", stdout=out)
    output = out.getvalue()
    assert "step 1" in output or "already up to date" in output

    doc = mongo_db["zones"].find_one({"_id": "zone-default"})
    assert doc is not None

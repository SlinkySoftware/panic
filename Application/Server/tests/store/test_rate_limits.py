"""``panic_server.store.rate_limits`` (DATA_MODEL.md §4.12): fixed-window ``$inc`` counters."""

from __future__ import annotations

import pytest
from pymongo.database import Database

from panic_server.store.rate_limits import increment

pytestmark = [pytest.mark.mongo]


def test_increment_counts_within_the_same_window(mongo_db: Database) -> None:
    key = "198.51.100.7"
    assert increment("login:ip", key, 60, db=mongo_db) == 1
    assert increment("login:ip", key, 60, db=mongo_db) == 2
    assert increment("login:ip", key, 60, db=mongo_db) == 3


def test_increment_is_isolated_per_bucket_and_key(mongo_db: Database) -> None:
    assert increment("login:user", "jdoe", 60, db=mongo_db) == 1
    assert increment("login:user", "other", 60, db=mongo_db) == 1
    assert increment("api:ip", "jdoe", 60, db=mongo_db) == 1


def test_increment_window_start_is_encoded_in_the_id(mongo_db: Database) -> None:
    increment("login:ip", "203.0.113.9", 60, db=mongo_db)
    doc = mongo_db["rate_limits"].find_one({"_id": {"$regex": "^login:ip:203.0.113.9:"}})
    assert doc is not None
    assert doc["count"] == 1
    assert "expire_at" in doc

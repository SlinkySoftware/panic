"""Scoped to ``tests/store``: every test here needs a real MongoDB (see ``tests/conftest.py``)."""

from __future__ import annotations

import pytest
from pymongo.database import Database

from panic_server.store.indexes import ensure_indexes


@pytest.fixture(scope="session", autouse=True)
def _ensure_store_indexes(mongo_db: Database) -> None:
    """Every repo query test relies on the real indexes existing (explain()-no-COLLSCAN, §4)."""
    ensure_indexes(mongo_db)

"""Server test configuration: every test runs against a fresh, seeded relational database."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from panic_server.state import STORE


@pytest.fixture(autouse=True)
def _db_backed_store(db: None) -> None:
    cache.clear()  # rate-limit counters
    STORE.simulation.active_user_id = "usr-admin"
    STORE.simulation.view_as_user_id = None
    STORE.reset()

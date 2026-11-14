"""Server test configuration: every test runs against a fresh, seeded relational database."""

from __future__ import annotations

import pytest

from panic_server.state import STORE


@pytest.fixture(autouse=True)
def _db_backed_store(db: None) -> None:
    STORE.simulation.active_user_id = "usr-admin"
    STORE.simulation.view_as_user_id = None
    STORE.reset()

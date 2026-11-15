"""Seeded fixtures get search keys like API-created resources, so palette and catalog search find them."""

from __future__ import annotations

from panic_server.fixtures import build_profile
from panic_server.management.commands.panic_seed import with_search_keys


def test_seeded_resources_are_searchable() -> None:
    f = build_profile("loadtest")
    item = with_search_keys("catalog", f.catalog[42])
    assert "load" in item.search_keys and "00042" in item.search_keys
    assert "list" in with_search_keys("lists", f.lists[0]).search_keys
    assert "dashboard" in with_search_keys("dashboards", f.dashboards[0]).search_keys
    assert "loaduser001" in with_search_keys("users", f.users[1]).search_keys
    assert with_search_keys("sites", f.sites[0]) == f.sites[0]

"""``store.repos.catalog`` / ``lists`` / ``dashboards`` / ``orphans`` (DATA_MODEL.md §4.5-4.7, §5.1)."""

from __future__ import annotations

import pytest
from pymongo.database import Database

from panic_common.visibility import VisibilitySpec
from panic_server.store.errors import NotFound
from panic_server.store.repos import catalog, dashboards, lists, orphans

pytestmark = [pytest.mark.mongo]


def test_catalog_item_crud_and_visibility(mongo_db: Database) -> None:
    item = catalog.create_catalog_item(
        mongo_db,
        title="core-rtr-01",
        host="rtr01.example.net",
        connections=[{"protocol": "SSH"}],
        normalized_keys=["ssh://rtr01.example.net:22"],
        created_by="jdoe",
        scope="PERSONAL",
        owner_usernames=["jdoe"],
    )
    assert item.version == 1
    assert item.orphaned is False

    fetched = catalog.get_catalog_item(mongo_db, item.id)
    assert fetched.host == "rtr01.example.net"

    dupes = catalog.find_by_normalized_keys(mongo_db, ["url://other:443", "ssh://rtr01.example.net:22"], "PERSONAL")
    assert [d.id for d in dupes] == [item.id]
    assert catalog.find_by_normalized_keys(mongo_db, ["ssh://rtr01.example.net:22"], "GLOBAL") == []

    updated = catalog.update_catalog_item(mongo_db, item.id, item.version, updated_by="jdoe", description="core router")
    assert updated.description == "core router"
    assert updated.updated_by == "jdoe"

    spec = VisibilitySpec(username="jdoe", team_ids=(), all_teams=False)
    visible = catalog.list_visible_catalog_items(mongo_db, spec)
    assert any(i.id == item.id for i in visible)

    other_spec = VisibilitySpec(username="someone_else", team_ids=(), all_teams=False)
    not_visible = catalog.list_visible_catalog_items(mongo_db, other_spec)
    assert all(i.id != item.id for i in not_visible)


def test_delete_catalog_item_pulls_from_lists(mongo_db: Database) -> None:
    item = catalog.create_catalog_item(
        mongo_db,
        title="to-delete",
        host="x.example.net",
        connections=[{"protocol": "URL"}],
        normalized_keys=["url://x.example.net"],
        created_by="jdoe",
    )
    a_list = lists.create_list(mongo_db, title="My List", created_by="jdoe", item_ids=[item.id])

    catalog.delete_catalog_item(mongo_db, item.id, item.version)

    after = lists.get_list(mongo_db, a_list.id)
    assert item.id not in after.item_ids
    assert after.version == a_list.version + 1

    with pytest.raises(NotFound):
        catalog.get_catalog_item(mongo_db, item.id)


def test_dashboards_crud_and_visibility(mongo_db: Database) -> None:
    dash = dashboards.create_dashboard(
        mongo_db,
        title="Network Ops",
        created_by="jdoe",
        scope="TEAM",
        team_ids=["team-net"],
        widgets=[{"id": "w-1", "widget_type": "HOST", "catalog_item_id": "whatever"}],
    )
    assert dash.widgets[0].id == "w-1"

    admin_spec = VisibilitySpec(username="admin", team_ids=(), all_teams=True)
    visible = dashboards.list_visible_dashboards(mongo_db, admin_spec)
    assert any(d.id == dash.id for d in visible)

    outsider_spec = VisibilitySpec(username="outsider", team_ids=(), all_teams=False)
    not_visible = dashboards.list_visible_dashboards(mongo_db, outsider_spec)
    assert all(d.id != dash.id for d in not_visible)


def test_orphans_list_and_set(mongo_db: Database) -> None:
    item = catalog.create_catalog_item(
        mongo_db,
        title="orphan-candidate",
        host="o.example.net",
        connections=[{"protocol": "SSH"}],
        normalized_keys=["ssh://o.example.net"],
        created_by="jdoe",
        scope="TEAM",
        team_ids=[],
        orphaned=True,
    )
    orphaned_docs = orphans.list_orphans(mongo_db, "catalog_items")
    assert any(d["_id"] == item.id for d in orphaned_docs)

    un_orphaned = orphans.set_orphaned(mongo_db, "catalog_items", item.id, False, item.version)
    assert un_orphaned["orphaned"] is False

    with pytest.raises(ValueError):
        orphans.list_orphans(mongo_db, "not_a_scoped_collection")


def test_recompute_orphans_on_user_change(mongo_db: Database) -> None:
    item = catalog.create_catalog_item(
        mongo_db,
        title="personal-orphan-recompute",
        host="p.example.net",
        connections=[{"protocol": "SSH"}],
        normalized_keys=["ssh://p.example.net"],
        created_by="retiree",
        scope="PERSONAL",
        owner_usernames=["retiree"],
        orphaned=False,
    )
    # "retiree" is no longer enabled: recompute should flip this PERSONAL item to orphaned.
    enabled = {"jdoe", "admin"}
    counts = orphans.recompute_orphans_on_user_change(mongo_db, enabled)
    assert counts["catalog_items"] >= 1
    after = catalog.get_catalog_item(mongo_db, item.id)
    assert after.orphaned is True

    # Re-enabling "retiree" should flip it back.
    orphans.recompute_orphans_on_user_change(mongo_db, enabled | {"retiree"})
    restored = catalog.get_catalog_item(mongo_db, item.id)
    assert restored.orphaned is False

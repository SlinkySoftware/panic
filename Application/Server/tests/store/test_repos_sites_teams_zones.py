"""``store.repos.sites`` / ``teams`` / ``zones`` (DATA_MODEL.md §4.2-4.4)."""

from __future__ import annotations

import time

import pytest
from pymongo.database import Database

from panic_server.store.errors import DuplicateKey, NotFound, VersionConflict
from panic_server.store.repos import sites, teams, zones

pytestmark = [pytest.mark.mongo]


# ---------------------------------------------------------------- sites
def test_sites_crud(mongo_db: Database) -> None:
    site = sites.create_site(mongo_db, code="syd", name="Sydney")
    assert site.code == "SYD"
    assert site.version == 1

    fetched = sites.get_site(mongo_db, site.id)
    assert fetched.name == "Sydney"

    by_code = sites.get_site_by_code(mongo_db, "SYD")
    assert by_code is not None
    assert by_code.id == site.id

    updated = sites.update_site(mongo_db, site.id, site.version, name="Sydney Metro")
    assert updated.name == "Sydney Metro"
    assert updated.version == 2

    with pytest.raises(VersionConflict):
        sites.update_site(mongo_db, site.id, site.version, name="stale")

    with pytest.raises(DuplicateKey):
        sites.create_site(mongo_db, code="SYD", name="Duplicate")

    sites.delete_site(mongo_db, site.id, updated.version)
    with pytest.raises(NotFound):
        sites.get_site(mongo_db, site.id)


# ---------------------------------------------------------------- teams
def test_teams_crud_never_stores_members(mongo_db: Database) -> None:
    team = teams.create_team(mongo_db, code="NETOPS", name="Network Operations")
    assert team.members == []  # Stage 6: membership lives only in users.team_ids
    raw = mongo_db["teams"].find_one({"_id": team.id})
    assert raw is not None
    assert "members" not in raw

    fetched = teams.get_team(mongo_db, team.id)
    assert fetched.name == "Network Operations"

    updated = teams.update_team(mongo_db, team.id, team.version, description="Core network team")
    assert updated.description == "Core network team"


def test_delete_team_pulls_references_and_orphans_bare_team_resources(mongo_db: Database) -> None:
    team = teams.create_team(mongo_db, code="TMPTEAM", name="Temp Team")
    user_doc_id = "usr-team-del-test"
    mongo_db["users"].insert_one({"_id": user_doc_id, "username": "teamdeltest", "team_ids": [team.id], "version": 1})
    item_id = "item-team-del-test"
    mongo_db["catalog_items"].insert_one(
        {"_id": item_id, "scope": "TEAM", "team_ids": [team.id], "orphaned": False, "version": 1, "title": "x"}
    )

    counts = teams.delete_team(mongo_db, team.id, team.version)
    assert counts["users"] == 1
    assert counts["catalog_items"] == 1
    assert counts["orphaned"] >= 1

    user_after = mongo_db["users"].find_one({"_id": user_doc_id})
    assert user_after is not None
    assert team.id not in user_after["team_ids"]

    item_after = mongo_db["catalog_items"].find_one({"_id": item_id})
    assert item_after is not None
    assert item_after["team_ids"] == []
    assert item_after["orphaned"] is True

    with pytest.raises(NotFound):
        teams.get_team(mongo_db, team.id)


# ---------------------------------------------------------------- zones
def test_default_zone_is_idempotent_and_protected(mongo_db: Database) -> None:
    first = zones.ensure_default_zone(mongo_db)
    second = zones.ensure_default_zone(mongo_db)
    assert first.id == zones.DEFAULT_ZONE_ID == second.id
    assert first.builtin is True

    with pytest.raises(ValueError):
        zones.update_zone(mongo_db, zones.DEFAULT_ZONE_ID, first.version, name="Renamed")
    with pytest.raises(ValueError):
        zones.delete_zone(mongo_db, zones.DEFAULT_ZONE_ID, first.version)


def test_zones_crud_and_cache(mongo_db: Database, settings) -> None:
    settings.PANIC_ZONE_CACHE_TTL_S = 10
    zones.invalidate_cache(mongo_db)
    before = {z.id for z in zones.list_zones(mongo_db)}

    zone = zones.create_zone(mongo_db, name="DMZ-test", cidrs=["10.1.0.0/24"])
    after_write = {z.id for z in zones.list_zones(mongo_db)}
    assert zone.id in after_write  # create_zone invalidates the cache itself
    assert after_write != before

    # Mutate the collection directly (bypassing the repo) -- the cache should still serve the
    # stale list until the TTL elapses or something calls invalidate_cache().
    mongo_db["zones"].delete_one({"_id": zone.id})
    cached = {z.id for z in zones.list_zones(mongo_db)}
    assert zone.id in cached

    zones.invalidate_cache(mongo_db)
    fresh = {z.id for z in zones.list_zones(mongo_db)}
    assert zone.id not in fresh


def test_zone_cache_expires_after_ttl(mongo_db: Database, settings) -> None:
    settings.PANIC_ZONE_CACHE_TTL_S = 0
    zones.invalidate_cache(mongo_db)
    zones.list_zones(mongo_db)
    zone = zones.create_zone(mongo_db, name="TTL-test-zone")
    time.sleep(0.01)
    names = {z.name for z in zones.list_zones(mongo_db)}
    assert zone.name in names
    settings.PANIC_ZONE_CACHE_TTL_S = 10

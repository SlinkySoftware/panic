"""``panic_seed`` / ``panic_export`` / ``panic_import`` against the Mongo-backed store (T-S6-03).

Supersedes two Stage 1-4, SQL-backed CLI tests that pinned the exact behaviour this task
replaces (``tests/test_store_db.py::test_panic_seed_is_idempotent`` and
``tests/test_server.py::test_export_then_import_on_clean_database_reproduces_state``), both
deleted alongside this file. See DATA_MODEL.md §7 and Documents/TASKS.md T-S6-03.
"""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from pymongo.database import Database

from panic_server.store.repos import catalog, dashboards, lists, sites, teams, users, zones

pytestmark = [pytest.mark.mongo]


def _seed(mongo_db: Database, profile: str, *, reset: bool = True) -> io.StringIO:
    out = io.StringIO()
    args = ["--profile", profile]
    if reset:
        args.append("--reset")
    call_command("panic_seed", *args, stdout=out)
    return out


def _export_to(mongo_db: Database, path: Path, *, shared_only: bool = False) -> dict:
    args = ["--output", str(path)]
    if shared_only:
        args.append("--shared-only")
    call_command("panic_export", *args)
    return json.loads(path.read_text(encoding="utf-8"))


def _non_default_zone_count(mongo_db: Database) -> int:
    return len([z for z in zones.list_zones(mongo_db) if z.id != zones.DEFAULT_ZONE_ID])


# ---------------------------------------------------------------- panic_seed


def test_seed_demo_profile_is_idempotent(mongo_db: Database) -> None:
    _seed(mongo_db, "demo")
    counts_1 = (
        len(sites.list_sites(mongo_db)),
        len(teams.list_teams(mongo_db)),
        _non_default_zone_count(mongo_db),
        len(users.list_users(mongo_db)),
        len(catalog.list_all_catalog_items(mongo_db)),
        len(lists.list_all_lists(mongo_db)),
        len(dashboards.list_all_dashboards(mongo_db)),
    )
    assert counts_1 == (4, 4, 4, 14, 19, 6, 5)

    # Re-running without --reset must not duplicate anything.
    _seed(mongo_db, "demo", reset=False)
    counts_2 = (
        len(sites.list_sites(mongo_db)),
        len(teams.list_teams(mongo_db)),
        _non_default_zone_count(mongo_db),
        len(users.list_users(mongo_db)),
        len(catalog.list_all_catalog_items(mongo_db)),
        len(lists.list_all_lists(mongo_db)),
        len(dashboards.list_all_dashboards(mongo_db)),
    )
    assert counts_2 == counts_1


def test_seed_loadtest_profile_produces_exact_counts(mongo_db: Database) -> None:
    _seed(mongo_db, "loadtest")
    assert len(sites.list_sites(mongo_db)) == 5
    assert len(teams.list_teams(mongo_db)) == 12
    assert _non_default_zone_count(mongo_db) == 20
    assert len(users.list_users(mongo_db)) == 50
    assert len(catalog.list_all_catalog_items(mongo_db)) == 5000
    assert len(lists.list_all_lists(mongo_db)) == 200
    assert len(dashboards.list_all_dashboards(mongo_db)) == 60


def test_seed_if_empty_skips_when_database_already_seeded(mongo_db: Database) -> None:
    _seed(mongo_db, "demo")
    out = io.StringIO()
    call_command("panic_seed", "--profile", "demo", "--if-empty", stdout=out)
    assert "skipping" in out.getvalue()
    # Nothing changed as a result.
    assert len(catalog.list_all_catalog_items(mongo_db)) == 19


def test_seed_reset_wipes_then_reseeds_canonical_values(mongo_db: Database) -> None:
    _seed(mongo_db, "demo")
    site = sites.get_site(mongo_db, "site-demo-dca")
    assert site.name == "Primary Datacenter"

    sites.update_site(mongo_db, site.id, site.version, name="Operator Edited")
    assert sites.get_site(mongo_db, site.id).name == "Operator Edited"

    # Re-seeding without --reset never overwrites an existing record.
    _seed(mongo_db, "demo", reset=False)
    assert sites.get_site(mongo_db, site.id).name == "Operator Edited"

    # --reset wipes first, so the canonical value comes back.
    _seed(mongo_db, "demo")
    assert sites.get_site(mongo_db, "site-demo-dca").name == "Primary Datacenter"


# ---------------------------------------------------------------- export / import


def _normalized(doc: dict) -> dict:
    """``doc`` with ``exported_at`` removed, for the byte-stability comparison."""
    out = copy.deepcopy(doc)
    out.pop("exported_at", None)
    return out


def test_export_import_export_round_trip_is_byte_stable_except_timestamp(
    mongo_db: Database, tmp_path: Path
) -> None:
    _seed(mongo_db, "demo")
    before = _export_to(mongo_db, tmp_path / "export1.json")

    call_command("panic_import", str(tmp_path / "export1.json"), "--replace")
    after = _export_to(mongo_db, tmp_path / "export2.json")

    assert _normalized(before) == _normalized(after)
    for section in ("sites", "teams", "zones", "users", "catalog", "lists", "dashboards"):
        assert before[section] == after[section], section
    assert before["system_settings"] == after["system_settings"]


def test_export_shared_only_drops_users_and_personal_items(mongo_db: Database, tmp_path: Path) -> None:
    _seed(mongo_db, "demo")
    doc = _export_to(mongo_db, tmp_path / "shared.json", shared_only=True)
    assert doc["shared_only"] is True
    assert doc["users"] == []
    for section in ("catalog", "lists", "dashboards"):
        assert all(o["scope"] != "PERSONAL" for o in doc[section]), section
        assert len(doc[section]) > 0  # GLOBAL/TEAM items from the demo fixture remain


def test_import_without_replace_upserts_by_id_and_leaves_unrelated_docs_alone(
    mongo_db: Database, tmp_path: Path
) -> None:
    _seed(mongo_db, "demo")
    unrelated = sites.create_site(mongo_db, code="ZZZ", name="Unrelated Site")

    partial_doc = {
        "format": "panic-export",
        "schema_version": 2,
        "server_version": "0.1.0",
        "exported_at": "2026-01-01T00:00:00Z",
        "shared_only": False,
        "sites": [
            {
                "id": "site-demo-dca",
                "code": "DC-A",
                "name": "Renamed By Import",
                "description": "Primary demo site.",
                "created_at": "2026-11-01T00:00:00Z",
                "updated_at": "2026-11-01T00:00:00Z",
                "version": 1,
            }
        ],
        "teams": [],
        "zones": [],
        "users": [],
        "catalog": [],
        "lists": [],
        "dashboards": [],
        "system_settings": None,
    }
    path = tmp_path / "partial.json"
    path.write_text(json.dumps(partial_doc), encoding="utf-8")

    out = io.StringIO()
    call_command("panic_import", str(path), stdout=out)
    assert "imported" in out.getvalue()

    assert sites.get_site(mongo_db, "site-demo-dca").name == "Renamed By Import"
    # The other three demo sites and the unrelated one are untouched.
    assert sites.get_site_by_code(mongo_db, "DC-B") is not None
    assert sites.get_site_by_code(mongo_db, "DC-C") is not None
    assert sites.get_site_by_code(mongo_db, "DC-D") is not None
    assert sites.get_site(mongo_db, unrelated.id).name == "Unrelated Site"


def test_import_with_replace_wipes_everything_first(mongo_db: Database, tmp_path: Path) -> None:
    _seed(mongo_db, "demo")
    export_doc = _export_to(mongo_db, tmp_path / "full.json")
    # Created after the export, so it is not part of the export document.
    sites.create_site(mongo_db, code="ZZZ", name="Unrelated Site")
    assert all(s["code"] != "ZZZ" for s in export_doc["sites"])

    call_command("panic_import", str(tmp_path / "full.json"), "--replace")

    assert sites.get_site_by_code(mongo_db, "ZZZ") is None
    assert sites.get_site_by_code(mongo_db, "DC-A") is not None


@pytest.mark.parametrize(
    "bad_doc",
    [
        {"format": "something-else", "schema_version": 2},
        {"format": "panic-export", "schema_version": 1},
        {"format": "panic-export", "schema_version": 999},
    ],
)
def test_import_rejects_malformed_or_wrong_schema_version(
    mongo_db: Database, tmp_path: Path, bad_doc: dict
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad_doc), encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("panic_import", str(path))

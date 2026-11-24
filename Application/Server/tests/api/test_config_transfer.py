"""Config export and merge-import (services/config_transfer.py) through the API, as a super admin.

Export and import cover the whole (shared, session-scoped) test database, so every assertion is on
records this test created (unique codes/titles), never on global counts.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.test import Client
from pymongo.database import Database

from panic_common.models import PermissionFlag
from panic_server.context import SESSION_USER_KEY
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]

PREVIEW = "/api/v1/admin/config/import/preview"
IMPORT = "/api/v1/admin/config/import"


def _sfx() -> str:
    return uuid.uuid4().hex[:8]


def _id() -> str:
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)


@pytest.fixture
def client(mongo_db: Database) -> Client:
    name = f"cfg-super-{_sfx()}"
    user = users_repo.create_user(
        mongo_db,
        username=name,
        display_name=name,
        default_remote_user=name,
        permissions=[str(PermissionFlag.SUPER_ADMIN), str(PermissionFlag.GLOBAL_ADMIN)],
    )
    c = Client()
    session = c.session
    session[SESSION_USER_KEY] = user.id
    session.save()
    c.cookies[django_settings.SESSION_COOKIE_NAME] = session.session_key
    return c


def _ssh(**extra: Any) -> dict[str, Any]:
    return {"protocol": "SSH", "port": None, "path_or_args": "", "custom_uri": "", **extra}


def _doc(**sections: list[dict[str, Any]]) -> dict[str, Any]:
    base: dict[str, Any] = {"format": "panic-config", "schema_version": 1}
    for s in ("sites", "teams", "zones", "catalog", "lists"):
        base[s] = sections.get(s, [])
    return base


def _site(code: str, name: str = "Site", rid: str | None = None) -> dict[str, Any]:
    return {"id": rid or _id(), "code": code, "name": name, "description": ""}


def _item(title: str, host: str, site: str, rid: str | None = None, **extra: Any) -> dict[str, Any]:
    rec = {
        "id": rid or _id(),
        "title": title,
        "description": "",
        "host": host,
        "connections": [_ssh()],
        "site": site,
        "account_override": "",
        "tags": [],
        "scope": "GLOBAL",
        "team_ids": [],
        "owner_usernames": [],
        "zone_ids": [],
    }
    rec.update(extra)
    return rec


def _create_item(db: Database, title: str, host: str, site: str, **extra: Any) -> Any:
    return catalog_repo.create_catalog_item(
        db,
        title=title,
        host=host,
        connections=[_ssh()],
        normalized_keys=[f"ssh://{host}:22"],
        created_by="system",
        site=site,
        **extra,
    )


def _preview(client: Client, doc: dict[str, Any]) -> dict[str, Any]:
    resp = client.post(PREVIEW, json.dumps(doc), content_type="application/json")
    assert resp.status_code == 200, resp.content
    return resp.json()


def _import(client: Client, doc: dict[str, Any], digest: str | None = None) -> Any:
    digest = digest if digest is not None else _preview(client, doc)["plan_digest"]
    return client.post(IMPORT, json.dumps({"document": doc, "plan_digest": digest}), content_type="application/json")


def _changes_for(preview: dict[str, Any], *ids: str) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in preview["changes"] if c["id"] in ids}


# ---------------------------------------------------------------- export


def test_export_shape_includes_personal_and_omits_users_and_dashboards(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    personal = _create_item(
        mongo_db, f"personal-{sfx}", f"p-{sfx}.example.com", "S1", scope="PERSONAL", owner_usernames=["someone"]
    )
    plist = lists_repo.create_list(
        mongo_db, title=f"plist-{sfx}", created_by="system", scope="PERSONAL", owner_usernames=["someone"]
    )
    dashboards_repo.create_dashboard(mongo_db, title=f"dash-{sfx}", created_by="system")

    doc = client.get("/api/v1/admin/config/export").json()
    assert doc["format"] == "panic-config" and doc["schema_version"] == 1
    assert {"sites", "teams", "zones", "catalog", "lists"} <= set(doc)
    assert "users" not in doc and "dashboards" not in doc and "system_settings" not in doc
    item = next(r for r in doc["catalog"] if r["id"] == personal.id)
    assert item["scope"] == "PERSONAL" and item["owner_usernames"] == ["someone"]
    assert set(item) == {
        "id",
        "title",
        "description",
        "host",
        "connections",
        "site",
        "account_override",
        "tags",
        "scope",
        "team_ids",
        "owner_usernames",
        "zone_ids",
    }  # no version, search/normalized keys, orphaned or audit fields
    assert any(r["id"] == plist.id for r in doc["lists"])


def test_round_trip_into_the_same_database_changes_nothing(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    site = sites_repo.create_site(mongo_db, code=f"RT{sfx}".upper(), name="Round trip")
    item = _create_item(mongo_db, f"rt-{sfx}", f"rt-{sfx}.example.com", site.code)
    doc = client.get("/api/v1/admin/config/export").json()
    preview = _preview(client, doc)
    assert _changes_for(preview, site.id, item.id) == {}  # both UNCHANGED, so not listed


# ---------------------------------------------------------------- ADD / UPDATE / references


def test_add_keeps_the_file_ids_and_references(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    site, team = _site(f"AD{sfx}".upper()), {"id": _id(), "code": f"T{sfx}".upper(), "name": "Team", "description": ""}
    zone = {
        "id": _id(),
        "name": f"zone-{sfx}",
        "description": "",
        "priority": 100,
        "cidrs": ["198.51.100.0/24"],
        "builtin": False,
    }
    item = _item(
        f"add-{sfx}", f"add-{sfx}.example.com", site["code"], scope="TEAM", team_ids=[team["id"]], zone_ids=[zone["id"]]
    )
    lst = {
        "id": _id(),
        "title": f"list-{sfx}",
        "description": "",
        "scope": "TEAM",
        "team_ids": [team["id"]],
        "owner_usernames": [],
        "item_ids": [item["id"]],
    }
    doc = _doc(sites=[site], teams=[team], zones=[zone], catalog=[item], lists=[lst])

    preview = _preview(client, doc)
    changes = _changes_for(preview, site["id"], team["id"], zone["id"], item["id"], lst["id"])
    assert {c["action"] for c in changes.values()} == {"ADD"} and len(changes) == 5

    resp = _import(client, doc, preview["plan_digest"])  # a preview with ADDs imports with its own digest
    assert resp.status_code == 200, resp.content
    assert resp.json()["summary"]["catalog"]["added"] >= 1

    assert sites_repo.get_site(mongo_db, site["id"]).code == site["code"]
    assert teams_repo.get_team(mongo_db, team["id"]).code == team["code"]
    assert zones_repo.get_zone(mongo_db, zone["id"]).cidrs == ["198.51.100.0/24"]
    stored = catalog_repo.get_catalog_item(mongo_db, item["id"])
    assert stored.team_ids == [team["id"]] and stored.zone_ids == [zone["id"]]
    assert stored.normalized_keys == [f"ssh://add-{sfx}.example.com:22"] and stored.search_keys
    assert lists_repo.get_list(mongo_db, lst["id"]).item_ids == [item["id"]]


def test_natural_key_match_updates_and_repoints_references(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    site = sites_repo.create_site(mongo_db, code=f"NK{sfx}".upper(), name="Old name")
    team = teams_repo.create_team(mongo_db, code=f"NT{sfx}".upper(), name="Team")
    zone = zones_repo.create_zone(mongo_db, name=f"nk-zone-{sfx}", cidrs=["192.0.2.0/24"])
    item = _create_item(mongo_db, f"nk-item-{sfx}", f"nk-{sfx}.example.com", site.code)
    lst = lists_repo.create_list(mongo_db, title=f"nk-list-{sfx}", created_by="system")

    # The same records as another install would export them: different ids, some values changed.
    f_site, f_team = _site(site.code, "New name"), {"id": _id(), "code": team.code, "name": "Team", "description": ""}
    f_zone = {
        "id": _id(),
        "name": zone.name,
        "description": "",
        "priority": 100,
        "cidrs": ["203.0.113.0/24"],
        "builtin": False,
    }
    f_item = _item(item.title, item.host, site.code, description="now described", zone_ids=[f_zone["id"]])
    f_list = {
        "id": _id(),
        "title": lst.title,
        "description": "",
        "scope": "GLOBAL",
        "team_ids": [],
        "owner_usernames": [],
        "item_ids": [f_item["id"]],
    }
    doc = _doc(sites=[f_site], teams=[f_team], zones=[f_zone], catalog=[f_item], lists=[f_list])

    changes = _changes_for(_preview(client, doc), f_site["id"], f_team["id"], f_zone["id"], f_item["id"], f_list["id"])
    assert changes[f_site["id"]]["action"] == "UPDATE" and changes[f_site["id"]]["fields"] == ["name"]
    assert f_team["id"] not in changes  # matched by code, nothing differs
    assert changes[f_zone["id"]]["fields"] == ["cidrs"]
    assert set(changes[f_item["id"]]["fields"]) == {"description", "zone_ids"}
    assert changes[f_list["id"]]["fields"] == ["item_ids"]

    assert _import(client, doc).status_code == 200
    assert sites_repo.get_site(mongo_db, site.id).name == "New name"
    stored = catalog_repo.get_catalog_item(mongo_db, item.id)
    assert stored.description == "now described" and stored.zone_ids == [zone.id]  # re-pointed to the match
    assert lists_repo.get_list(mongo_db, lst.id).item_ids == [item.id]
    # Matched, so nothing was added under the file's ids.
    assert all(s.id != f_site["id"] for s in sites_repo.list_sites(mongo_db))
    assert not catalog_repo.get_catalog_items_by_ids(mongo_db, [f_item["id"]])
    assert not lists_repo.get_lists_by_ids(mongo_db, [f_list["id"]])


def test_personal_items_match_by_title_and_owners(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    mine = _create_item(
        mongo_db, f"lab-{sfx}", f"lab-{sfx}.example.com", "S1", scope="PERSONAL", owner_usernames=["alice"]
    )
    same_owner = _item(mine.title, mine.host, "S1", scope="PERSONAL", owner_usernames=["alice"], description="x")
    other_owner = _item(mine.title, mine.host, "S1", scope="PERSONAL", owner_usernames=["bob"])
    changes = _changes_for(
        _preview(client, _doc(catalog=[same_owner, other_owner])), same_owner["id"], other_owner["id"]
    )
    assert changes[same_owner["id"]]["action"] == "UPDATE"
    assert changes[other_owner["id"]]["action"] == "ADD"


# ---------------------------------------------------------------- conflicts


def test_ambiguous_match_is_a_conflict_and_writes_nothing(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    a = _create_item(mongo_db, f"twin-{sfx}", f"a-{sfx}.example.com", "S1")
    b = _create_item(mongo_db, f"twin-{sfx}", f"b-{sfx}.example.com", "S1")
    f_item = _item(f"twin-{sfx}", f"c-{sfx}.example.com", "S1", description="changed")
    doc = _doc(catalog=[f_item])
    change = _changes_for(_preview(client, doc), f_item["id"])[f_item["id"]]
    assert change["action"] == "CONFLICT" and "2 existing records" in change["reason"]
    assert _import(client, doc).status_code == 200
    assert catalog_repo.get_catalog_item(mongo_db, a.id).description == ""
    assert catalog_repo.get_catalog_item(mongo_db, b.id).description == ""
    assert not catalog_repo.get_catalog_items_by_ids(mongo_db, [f_item["id"]])


def test_site_code_taken_by_another_site_is_a_conflict(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    s1 = sites_repo.create_site(mongo_db, code=f"C1{sfx}".upper(), name="One")
    s2 = sites_repo.create_site(mongo_db, code=f"C2{sfx}".upper(), name="Two")
    doc = _doc(sites=[_site(s2.code, "One renamed", rid=s1.id)])  # s1 by id, but s2's code
    change = _changes_for(_preview(client, doc), s1.id)[s1.id]
    assert change["action"] == "CONFLICT" and s2.code in change["reason"]
    assert _import(client, doc).status_code == 200
    assert sites_repo.get_site(mongo_db, s1.id).code == s1.code


@pytest.mark.parametrize(
    "connections",
    [
        [_ssh(), {"protocol": "RDP", "port": None, "path_or_args": "", "custom_uri": ""}],
        [_ssh(path_or_args="-pw hunter2")],
    ],
)
def test_invalid_items_are_conflicts(mongo_db: Database, client: Client, connections: list[dict[str, Any]]) -> None:
    sfx = _sfx()
    f_item = _item(f"bad-{sfx}", f"bad-{sfx}.example.com", "S1", connections=connections)
    doc = _doc(catalog=[f_item])
    assert _changes_for(_preview(client, doc), f_item["id"])[f_item["id"]]["action"] == "CONFLICT"
    assert _import(client, doc).status_code == 200
    assert not catalog_repo.get_catalog_items_by_ids(mongo_db, [f_item["id"]])


# ---------------------------------------------------------------- special cases


def test_site_renamed_by_id_renames_it_on_items(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    site = sites_repo.create_site(mongo_db, code=f"OLD{sfx}".upper(), name="Site")
    item = _create_item(mongo_db, f"on-site-{sfx}", f"os-{sfx}.example.com", site.code)
    new_code = f"NEW{sfx}".upper()
    assert _import(client, _doc(sites=[_site(new_code, "Site", rid=site.id)])).status_code == 200
    assert sites_repo.get_site(mongo_db, site.id).code == new_code
    assert catalog_repo.get_catalog_item(mongo_db, item.id).site == new_code


def test_builtin_default_zone_only_takes_the_description(mongo_db: Database, client: Client) -> None:
    before = zones_repo.get_zone(mongo_db, zones_repo.DEFAULT_ZONE_ID)
    desc = f"described-{_sfx()}"
    f_zone = {
        "id": before.id,
        "name": "Renamed default",
        "description": desc,
        "priority": 1,
        "cidrs": ["10.0.0.0/8"],
        "builtin": True,
    }
    try:
        assert _import(client, _doc(zones=[f_zone])).status_code == 200
        after = zones_repo.get_zone(mongo_db, before.id)
        assert after.description == desc
        assert (after.name, after.priority, after.cidrs, after.builtin) == (
            before.name,
            before.priority,
            before.cidrs,
            True,
        )
    finally:
        zones_repo.upsert_zone(mongo_db, before)


def test_stale_digest_is_409_and_writes_nothing(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    f_site = _site(f"ST{sfx}".upper())
    resp = _import(client, _doc(sites=[f_site]), digest="0" * 64)
    assert resp.status_code == 409 and resp.json()["error_code"] == "VERSION_CONFLICT"
    assert sites_repo.get_site_by_code(mongo_db, f_site["code"]) is None


def test_data_changed_after_preview_is_409(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    site = sites_repo.create_site(mongo_db, code=f"CH{sfx}".upper(), name="Before")
    doc = _doc(sites=[_site(site.code, "From file", rid=site.id)])
    digest = _preview(client, doc)["plan_digest"]
    sites_repo.update_site(mongo_db, site.id, site.version, name="Someone else")  # the plan is now different
    assert _import(client, doc, digest).status_code == 409
    assert sites_repo.get_site(mongo_db, site.id).name == "Someone else"


def test_import_is_idempotent_and_never_deletes(mongo_db: Database, client: Client) -> None:
    sfx = _sfx()
    untouched = sites_repo.create_site(mongo_db, code=f"KEEP{sfx}".upper(), name="Not in file")
    f_site = _site(f"IDEM{sfx}".upper())
    f_item = _item(f"idem-{sfx}", f"idem-{sfx}.example.com", f_site["code"])
    doc = _doc(sites=[f_site], catalog=[f_item])
    assert _import(client, doc).status_code == 200
    assert _changes_for(_preview(client, doc), f_site["id"], f_item["id"]) == {}  # second time: all unchanged
    assert _import(client, doc).status_code == 200
    assert sites_repo.get_site(mongo_db, untouched.id).code == untouched.code


def test_import_is_audited(mongo_db: Database, client: Client) -> None:
    f_site = _site(f"AU{_sfx()}".upper())
    assert _import(client, _doc(sites=[f_site])).status_code == 200
    entries = client.get("/api/v1/audit?action=admin.config.import").json()["results"]
    assert any(any(c["id"] == f_site["id"] for c in e["details"].get("changes", [])) for e in entries), (
        "no admin.config.import audit entry lists the added site"
    )


def test_bad_documents_are_400(client: Client) -> None:
    for doc in ({"format": "panic-export", "schema_version": 2}, {"format": "panic-config", "schema_version": 9}, [1]):
        resp = client.post(PREVIEW, json.dumps(doc), content_type="application/json")
        assert resp.status_code == 400, doc
        assert resp.json()["error_code"] == "VALIDATION_ERROR"

"""``./panic addexamples`` / ``delexamples``: add next to real data, re-run safely, and remove only the
example documents plus the references real data picked up."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.management import call_command

from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import users as users_repo


def _count(db: Any, coll: str) -> int:
    return db[coll].count_documents({"_id": {"$regex": "^example-"}})


def test_add_is_idempotent_and_remove_leaves_real_data_clean(mongo_db: Any) -> None:
    call_command("panic_examples", "add")
    n_items = _count(mongo_db, catalog_repo.COLLECTION)
    assert n_items > 0 and _count(mongo_db, "users") > 0 and _count(mongo_db, "zones") > 0
    call_command("panic_examples", "add")  # re-run: replaced, nothing duplicated
    assert _count(mongo_db, catalog_repo.COLLECTION) == n_items

    ex_item = mongo_db[catalog_repo.COLLECTION].find_one({"_id": {"$regex": "^example-"}})
    ex_list = mongo_db[lists_repo.COLLECTION].find_one({"_id": {"$regex": "^example-"}})
    ex_dash = mongo_db[dashboards_repo.COLLECTION].find_one({"_id": {"$regex": "^example-"}})
    ex_zone = mongo_db["zones"].find_one({"_id": {"$regex": "^example-"}})
    ex_team = mongo_db["teams"].find_one({"_id": {"$regex": "^example-"}})
    tag = uuid.uuid4().hex[:6]

    # Real data that references example data.
    real_user = users_repo.create_user(
        mongo_db, username=f"real-{tag}", display_name="Real", default_remote_user="real", team_ids=[ex_team["_id"]]
    )
    mongo_db["users"].update_one(
        {"_id": real_user.id},
        {"$set": {"pinned_dashboard_ids": [ex_dash["_id"]], "default_dashboard_id": ex_dash["_id"]}},
    )
    real_item = catalog_repo.create_catalog_item(
        mongo_db,
        title=f"real {tag}",
        protocol="SSH",
        host=f"real-{tag}.example.org",
        port=22,
        site="S1",
        normalized_key=f"ssh://real-{tag}.example.org:22",
        scope="GLOBAL",
        created_by="real",
        zone_ids=[ex_zone["_id"]],
    )
    real_list = lists_repo.create_list(
        mongo_db, title=f"real list {tag}", created_by="real", scope="GLOBAL", item_ids=[real_item.id, ex_item["_id"]]
    )
    real_dash = dashboards_repo.create_dashboard(
        mongo_db,
        title=f"real dash {tag}",
        created_by="real",
        scope="GLOBAL",
        widgets=[
            {
                "id": "w-real",
                "widget_type": "HOST",
                "title": "",
                "grid_x": 1,
                "grid_y": 1,
                "grid_w": 4,
                "grid_h": 1,
                "catalog_item_id": real_item.id,
                "list_id": None,
            },
            {
                "id": "w-ex",
                "widget_type": "LIST",
                "title": "",
                "grid_x": 5,
                "grid_y": 1,
                "grid_w": 4,
                "grid_h": 1,
                "catalog_item_id": None,
                "list_id": ex_list["_id"],
            },
        ],
    )

    call_command("panic_examples", "remove")

    for coll in (catalog_repo.COLLECTION, lists_repo.COLLECTION, dashboards_repo.COLLECTION, "users", "teams", "zones"):
        assert _count(mongo_db, coll) == 0, coll
    assert lists_repo.get_list(mongo_db, real_list.id).item_ids == [real_item.id]
    assert [w.id for w in dashboards_repo.get_dashboard(mongo_db, real_dash.id).widgets] == ["w-real"]
    assert catalog_repo.get_catalog_item(mongo_db, real_item.id).zone_ids == []
    u = users_repo.get_user(mongo_db, real_user.id)
    assert u.team_ids == [] and u.pinned_dashboard_ids == [] and u.default_dashboard_id is None


def test_add_replaces_an_older_example_version_and_refuses_real_clashes(mongo_db: Any) -> None:
    import pytest
    from django.core.management import CommandError

    from panic_server.store.repos import teams as teams_repo

    # An older dataset version: same code, different id (the bug this guards against).
    mongo_db["teams"].insert_one({"_id": "example-team-old", "code": "EX-NETOPS", "name": "old", "version": 1})
    call_command("panic_examples", "add")
    assert mongo_db["teams"].count_documents({"_id": "example-team-old"}) == 0
    assert mongo_db["teams"].count_documents({"code": "EX-NETOPS"}) == 1
    call_command("panic_examples", "remove")

    # Real data holding an example code: refuse, write nothing.
    real = teams_repo.create_team(mongo_db, code="EX-SECOPS", name="Real team")
    with pytest.raises(CommandError, match="EX-SECOPS"):
        call_command("panic_examples", "add")
    assert _count(mongo_db, catalog_repo.COLLECTION) == 0
    mongo_db["teams"].delete_one({"_id": real.id})

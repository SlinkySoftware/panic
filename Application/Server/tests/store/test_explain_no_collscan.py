"""Acceptance: every repository query, run against a small reference dataset, uses an index
(no ``COLLSCAN`` anywhere in the ``explain()`` plan tree) -- DATA_MODEL.md §4.
"""

from __future__ import annotations

from typing import Any

import pytest
from pymongo.database import Database

from panic_common.visibility import VisibilitySpec
from panic_server.store.filters import visibility_filter
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import orphans as orphans_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]


def _plan_stages(explain_output: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten every stage dict anywhere in an ``explain()`` output's plan tree(s)."""
    stages: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            stages.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    qp = explain_output.get("queryPlanner", {})
    walk(qp.get("winningPlan"))
    for shard in explain_output.get("shards", {}).values() if isinstance(explain_output.get("shards"), dict) else []:
        walk(shard.get("queryPlanner", {}).get("winningPlan"))
    return stages


def _assert_no_collscan(explain_output: dict[str, Any], label: str) -> None:
    stages = _plan_stages(explain_output)
    stage_names = {s.get("stage") for s in stages if "stage" in s}
    assert "COLLSCAN" not in stage_names, f"{label}: COLLSCAN in plan ({stage_names})"


@pytest.fixture(scope="module")
def seeded(mongo_db: Database) -> Database:
    """A handful of documents per collection -- enough for explain() to pick a real plan."""
    users_repo.create_user(mongo_db, username="explain_user", display_name="E", default_remote_user="e")
    catalog_repo.create_catalog_item(
        mongo_db,
        title="explain-item",
        host="explain.example.net",
        connections=[{"protocol": "SSH"}],
        normalized_keys=["ssh://explain.example.net"],
        created_by="explain_user",
        scope="GLOBAL",
    )
    lists_repo.create_list(mongo_db, title="explain-list", created_by="explain_user", scope="GLOBAL")
    dashboards_repo.create_dashboard(mongo_db, title="explain-dash", created_by="explain_user", scope="GLOBAL")
    audit_repo.append_audit(
        mongo_db,
        actor_username="explain_user",
        action="catalog.create",
        target_type="catalog_item",
        target_id="x",
        summary="x",
        client_ip="127.0.0.1",
    )
    zones_repo.ensure_default_zone(mongo_db)
    return mongo_db


def test_users_by_username_and_team_use_an_index(seeded: Database) -> None:
    _assert_no_collscan(seeded["users"].find({"username": "explain_user"}).explain(), "users.by_username")
    _assert_no_collscan(seeded["users"].find({"team_ids": "team-x"}).explain(), "users.by_team_ids")


def test_catalog_visibility_query_uses_an_index(seeded: Database) -> None:
    spec = VisibilitySpec(username="explain_user", team_ids=(), all_teams=False)
    query = visibility_filter(spec)
    plan = seeded["catalog_items"].find(query).sort([("scope", 1), ("title", 1)]).explain()
    _assert_no_collscan(plan, "catalog_items.visibility")


def test_catalog_normalized_key_lookup_uses_an_index(seeded: Database) -> None:
    query = {"normalized_keys": {"$in": ["ssh://explain.example.net"]}, "scope": "GLOBAL"}
    _assert_no_collscan(seeded["catalog_items"].find(query).explain(), "catalog_items.normalized_keys")


def test_catalog_protocol_filter_uses_an_index(seeded: Database) -> None:
    plan = seeded["catalog_items"].find({"connections.protocol": "URL"}).explain()
    _assert_no_collscan(plan, "catalog_items.connections_protocol")


def test_endpoint_lists_visibility_query_uses_an_index(seeded: Database) -> None:
    spec = VisibilitySpec(username="explain_user", team_ids=(), all_teams=False)
    plan = seeded["endpoint_lists"].find(visibility_filter(spec)).sort([("scope", 1), ("title", 1)]).explain()
    _assert_no_collscan(plan, "endpoint_lists.visibility")


def test_dashboards_visibility_query_uses_an_index(seeded: Database) -> None:
    spec = VisibilitySpec(username="explain_user", team_ids=(), all_teams=True)
    plan = seeded["dashboards"].find(visibility_filter(spec)).sort([("scope", 1), ("sort_order", 1)]).explain()
    _assert_no_collscan(plan, "dashboards.visibility")


def test_orphans_query_uses_an_index(seeded: Database) -> None:
    for collection in orphans_repo.SCOPED_COLLECTIONS:
        plan = seeded[collection].find({"orphaned": True}).explain()
        _assert_no_collscan(plan, f"{collection}.orphans")


def test_audit_log_keyset_and_actor_queries_use_an_index(seeded: Database) -> None:
    plan = seeded["audit_log"].find({}).sort([("created_at", -1), ("_id", -1)]).explain()
    _assert_no_collscan(plan, "audit_log.keyset")

    plan2 = seeded["audit_log"].find({"actor_username": "explain_user"}).sort([("created_at", -1)]).explain()
    _assert_no_collscan(plan2, "audit_log.by_actor")


def test_zones_and_sites_and_teams_lookups_use_an_index(seeded: Database) -> None:
    _assert_no_collscan(seeded["zones"].find({"name": zones_repo.DEFAULT_ZONE_NAME}).explain(), "zones.by_name")
    _assert_no_collscan(seeded["sites"].find({"code": "SYD"}).explain(), "sites.by_code")
    _assert_no_collscan(seeded["teams"].find({"code": "NETOPS"}).explain(), "teams.by_code")

"""``GET /api/v1/ui/{bootstrap,dashboards/{id},search}`` and the ``.rdp`` download (API.md §4.2,
§4.3, closes F3) against a real Mongo-backed scenario.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.test import Client, override_settings
from pymongo.database import Database

from panic_common.models import PermissionFlag, Protocol, ScopeType, UnreachablePolicy
from panic_common.search_keys import search_keys
from panic_server.context import SESSION_USER_KEY
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]


def _client_as(user_id: str) -> Client:
    client = Client()
    session = client.session
    session[SESSION_USER_KEY] = user_id
    session.save()
    client.cookies[django_settings.SESSION_COOKIE_NAME] = session.session_key
    return client


@pytest.fixture
def scenario(mongo_db: Database) -> dict[str, Any]:
    """A small, deliberately varied scenario: visible/invisible items, a restricted zone, a
    list, and a dashboard referencing all of the above (including a dangling, invisible ref).

    Unique-suffixed usernames/zone names: this fixture is function-scoped (some tests mutate the
    user) and re-invoked by every test in this module, so fixed names would collide with the
    ``users.username_unique``/``zones.name_unique`` indexes across that many calls.
    """
    suffix = uuid.uuid4().hex[:8]
    zones_repo.ensure_default_zone(mongo_db)
    restricted_zone = zones_repo.create_zone(mongo_db, name=f"ui-test-restricted-{suffix}", cidrs=["203.0.113.0/24"])

    team_id = "team-ui-test"
    plain_username = f"ui-plain-{suffix}"
    admin_username = f"ui-admin-{suffix}"
    plain = users_repo.create_user(
        mongo_db,
        username=plain_username,
        display_name="UI Plain",
        default_remote_user=plain_username,
        team_ids=[team_id],
    )
    admin = users_repo.create_user(
        mongo_db,
        username=admin_username,
        display_name="UI Admin",
        default_remote_user=admin_username,
        permissions=[str(PermissionFlag.GLOBAL_ADMIN)],
    )

    ssh_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="core-sw-01",
        protocol=str(Protocol.SSH),
        host="core-sw-01.example.com",
        port=22,
        site="2SYA",
        normalized_key="ssh://core-sw-01.example.com:22",
        created_by="system",
        tags=["network"],
        search_keys=search_keys("core-sw-01", "core-sw-01.example.com", "2SYA", ["network"]),
    )
    restricted_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="restricted-box",
        protocol=str(Protocol.SSH),
        host="restricted.example.com",
        port=22,
        site="2SYA",
        normalized_key="ssh://restricted.example.com:22",
        created_by="system",
        zone_ids=[restricted_zone.id],
        search_keys=search_keys("restricted-box", "restricted.example.com", "2SYA"),
    )
    rdp_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="jump-rdp",
        protocol=str(Protocol.RDP),
        host="jump.example.com",
        port=3389,
        site="2SYA",
        normalized_key="rdp://jump.example.com:3389",
        created_by="system",
        search_keys=search_keys("jump-rdp", "jump.example.com", "2SYA"),
    )
    personal_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="someone-elses-box",
        protocol=str(Protocol.SSH),
        host="personal.example.com",
        port=22,
        site="2SYA",
        normalized_key="ssh://personal.example.com:22",
        created_by="system",
        scope=str(ScopeType.PERSONAL),
        owner_usernames=["someone-else"],
        search_keys=search_keys("someone-elses-box", "personal.example.com", "2SYA"),
    )

    endpoint_list = lists_repo.create_list(
        mongo_db,
        title="Core Switches",
        created_by="system",
        item_ids=[ssh_item.id, restricted_item.id],
        search_keys=search_keys("Core Switches", "", ""),
    )

    dashboard = dashboards_repo.create_dashboard(
        mongo_db,
        title="Network Ops",
        created_by="system",
        always_display=True,
        widgets=[
            {"id": "w-1", "widget_type": "HOST", "catalog_item_id": ssh_item.id},
            {"id": "w-2", "widget_type": "HOST", "catalog_item_id": personal_item.id},
            {"id": "w-3", "widget_type": "HOST", "catalog_item_id": rdp_item.id},
            {"id": "w-4", "widget_type": "LIST", "list_id": endpoint_list.id},
        ],
        search_keys=search_keys("Network Ops", "", ""),
    )

    team_dashboard = dashboards_repo.create_dashboard(
        mongo_db, title="Other Team Only", created_by="system", scope=str(ScopeType.TEAM), team_ids=["team-not-mine"]
    )

    return {
        "plain": plain,
        "admin": admin,
        "ssh_item": ssh_item,
        "restricted_item": restricted_item,
        "rdp_item": rdp_item,
        "personal_item": personal_item,
        "list": endpoint_list,
        "dashboard": dashboard,
        "team_dashboard": team_dashboard,
    }


# ---------------------------------------------------------------- bootstrap


def test_bootstrap_shape_for_plain_user(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get("/api/v1/ui/bootstrap")
    assert resp.status_code == 200
    body = resp.json()

    assert body["me"]["username"] == scenario["plain"].username
    assert body["real_user"] is None
    assert body["view_as"] is None
    assert body["permissions"] == {
        "global_admin": False,
        "can_add_global": False,
        "can_add_team": False,
        "can_view_as": False,
    }
    assert body["client"]["zone"]["id"] == zones_repo.DEFAULT_ZONE_ID
    assert body["client"]["zone_source"] == "DEFAULT"

    nav_ids = {d["id"] for d in body["nav"]["dashboards"]}
    assert scenario["dashboard"].id in nav_ids  # always_display
    assert scenario["team_dashboard"].id not in nav_ids  # not visible (different team)

    assert body["default_dashboard"] is not None


def test_bootstrap_permissions_for_admin(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["admin"].id)
    body = client.get("/api/v1/ui/bootstrap").json()
    assert body["permissions"]["global_admin"] is True
    assert body["permissions"]["can_view_as"] is True


# ---------------------------------------------------------------- dashboard view


def test_dashboard_view_resolves_items_lists_and_unavailable(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/ui/dashboards/{scenario['dashboard'].id}")
    assert resp.status_code == 200
    assert resp.has_header("ETag")
    body = resp.json()

    assert body["dashboard"]["id"] == scenario["dashboard"].id
    assert body["dashboard"]["is_global_default"] is False

    ssh_id, personal_id, rdp_id = scenario["ssh_item"].id, scenario["personal_item"].id, scenario["rdp_item"].id
    assert ssh_id in body["items"]
    assert rdp_id in body["items"]
    assert body["items"][rdp_id]["launch"]["kind"] == "DOWNLOAD"
    assert body["items"][rdp_id]["launch"]["href"] == f"/api/v1/launch/rdp/{rdp_id}.rdp"
    assert body["items"][ssh_id]["launch"]["kind"] == "COPY"
    assert f"{scenario['plain'].default_remote_user}@" in body["items"][ssh_id]["launch"]["command"]

    # personal_item belongs to someone else: invisible, so it is a dangling widget reference.
    assert personal_id not in body["items"]
    assert personal_id in body["unavailable"]["items"]

    assert scenario["list"].id in body["lists"]
    assert body["lists"][scenario["list"].id]["item_count"] == 2


def test_dashboard_view_etag_304_on_if_none_match(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    first = client.get(f"/api/v1/ui/dashboards/{scenario['dashboard'].id}")
    etag = first["ETag"]

    second = client.get(f"/api/v1/ui/dashboards/{scenario['dashboard'].id}", HTTP_IF_NONE_MATCH=etag)
    assert second.status_code == 304
    assert second.content == b""


def test_dashboard_view_invisible_dashboard_is_404_not_403(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/ui/dashboards/{scenario['team_dashboard'].id}")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


def test_dashboard_view_unknown_id_is_404(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get("/api/v1/ui/dashboards/does-not-exist")
    assert resp.status_code == 404


def test_dashboard_view_hide_policy_omits_unreachable_item(mongo_db: Database, scenario: dict[str, Any]) -> None:
    users_repo.update_user(
        mongo_db, scenario["plain"].id, scenario["plain"].version, unreachable_policy=str(UnreachablePolicy.HIDE)
    )
    client = _client_as(scenario["plain"].id)
    body = client.get(f"/api/v1/ui/dashboards/{scenario['dashboard'].id}").json()
    assert scenario["restricted_item"].id not in body["items"]
    assert scenario["restricted_item"].id not in body["lists"][scenario["list"].id]["item_ids"]


# ---------------------------------------------------------------- search


def test_search_requires_two_characters(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    assert client.get("/api/v1/ui/search?q=c").json()["results"] == []


def test_search_finds_item_dashboard_and_list_by_prefix(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    body = client.get("/api/v1/ui/search?q=core").json()
    types_and_ids = {(r["type"], r["id"]) for r in body["results"]}
    assert ("ITEM", scenario["ssh_item"].id) in types_and_ids
    assert ("LIST", scenario["list"].id) in types_and_ids
    for result in body["results"]:
        if result["type"] == "ITEM":
            assert result["item"] is not None


def test_search_never_returns_invisible_personal_item(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    body = client.get("/api/v1/ui/search?q=someone").json()
    assert body["results"] == []


# ---------------------------------------------------------------- .rdp download


def test_rdp_href_carries_the_base_path(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    rdp_id = scenario["rdp_item"].id
    with override_settings(PANIC_BASE_PATH="/panic"):
        resp = client.get(f"/api/v1/ui/dashboards/{scenario['dashboard'].id}", SCRIPT_NAME="/panic")
    assert resp.status_code == 200
    assert resp.json()["items"][rdp_id]["launch"]["href"] == f"/panic/api/v1/launch/rdp/{rdp_id}.rdp"


def test_rdp_download_succeeds_and_is_audited(mongo_db: Database, scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/launch/rdp/{scenario['rdp_item'].id}.rdp")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/x-rdp"
    assert resp["Cache-Control"] == "no-store"
    assert "attachment" in resp["Content-Disposition"]
    assert b"full address:s:jump.example.com:3389" in resp.content

    actions = [a.action for a in audit_repo.list_audit(mongo_db, action="launch.rdp.download", limit=10)]
    assert "launch.rdp.download" in actions


def test_rdp_download_user_override(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/launch/rdp/{scenario['rdp_item'].id}.rdp?user=overridden")
    assert b"username:s:overridden" in resp.content


def test_rdp_download_404_for_non_rdp_item(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/launch/rdp/{scenario['ssh_item'].id}.rdp")
    assert resp.status_code == 404


def test_rdp_download_404_for_invisible_item(scenario: dict[str, Any]) -> None:
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/launch/rdp/{scenario['personal_item'].id}.rdp")
    assert resp.status_code == 404


def test_rdp_download_404_when_unreachable_and_hide_policy(mongo_db: Database, scenario: dict[str, Any]) -> None:
    rdp_restricted = catalog_repo.create_catalog_item(
        mongo_db,
        title="restricted-rdp",
        protocol=str(Protocol.RDP),
        host="restricted-rdp.example.com",
        port=3389,
        normalized_key="rdp://restricted-rdp.example.com:3389",
        created_by="system",
        zone_ids=[scenario["restricted_item"].zone_ids[0]],
    )
    users_repo.update_user(
        mongo_db, scenario["plain"].id, scenario["plain"].version, unreachable_policy=str(UnreachablePolicy.HIDE)
    )
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/launch/rdp/{rdp_restricted.id}.rdp")
    assert resp.status_code == 404


def test_rdp_download_200_when_unreachable_and_dim_policy(mongo_db: Database, scenario: dict[str, Any]) -> None:
    rdp_restricted = catalog_repo.create_catalog_item(
        mongo_db,
        title="restricted-rdp-2",
        protocol=str(Protocol.RDP),
        host="restricted-rdp-2.example.com",
        port=3389,
        normalized_key="rdp://restricted-rdp-2.example.com:3389",
        created_by="system",
        zone_ids=[scenario["restricted_item"].zone_ids[0]],
    )
    # scenario["plain"]'s default unreachable_policy is DIM.
    client = _client_as(scenario["plain"].id)
    resp = client.get(f"/api/v1/launch/rdp/{rdp_restricted.id}.rdp")
    assert resp.status_code == 200

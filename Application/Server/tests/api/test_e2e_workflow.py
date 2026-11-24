"""End-to-end workflow against the real Mongo-backed stack: sign in -> dashboard -> edit layout ->
list edit -> catalog -> admin -> audit. One long, realistic session through real HTTP, asserting
each step's effect is visible in the next and that the audit trail records the whole journey.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client

from panic_common.models import PermissionFlag
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _call(client: Client, method: str, path: str, body: dict[str, Any] | None = None, **extra: str) -> Any:
    kwargs: dict[str, Any] = dict(extra)
    if body is not None:
        kwargs["data"] = json.dumps(body)
        kwargs["content_type"] = "application/json"
    resp = getattr(client, method)(path, **kwargs)
    return resp


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Any) -> None:
    zones_repo.ensure_default_zone(mongo_db)


def test_full_workflow_sign_in_through_audit(mongo_db: Any) -> None:
    username = _unique("e2e-admin")
    password = "correct-horse-battery-staple"

    users_repo.create_user(
        mongo_db,
        username=username,
        display_name="E2E Admin",
        default_remote_user=username,
        permissions=[str(PermissionFlag.GLOBAL_ADMIN)],
    )
    users_repo.set_password_hash(mongo_db, username, make_password(password), auth_source="LOCAL")

    client = Client()

    # ---------------------------------------------------------------- sign in
    login_resp = _call(client, "post", "/api/v1/auth/login", {"username": username, "password": password})
    assert login_resp.status_code == 200, login_resp.content
    assert login_resp.json()["me"]["username"] == username

    bootstrap = _call(client, "get", "/api/v1/ui/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["permissions"]["global_admin"] is True

    # ---------------------------------------------------------------- dashboard create + layout edit
    create_dash = _call(
        client, "post", "/api/v1/dashboards", {"title": "E2E Dashboard", "scope": "GLOBAL", "description": "e2e"}
    )
    assert create_dash.status_code == 201, create_dash.content
    dashboard = create_dash.json()
    assert dashboard["version"] == 1

    create_item = _call(
        client,
        "post",
        "/api/v1/catalog",
        {
            "title": "e2e-router",
            "host": "e2e-router.example.com",
            "connections": [{"protocol": "SSH", "port": 22}],
            "scope": "GLOBAL",
        },
    )
    assert create_item.status_code == 201, create_item.content
    item = create_item.json()

    layout_resp = _call(
        client,
        "put",
        f"/api/v1/dashboards/{dashboard['id']}/layout",
        {
            "widgets": [
                {
                    "widget_type": "HOST",
                    "catalog_item_id": item["id"],
                    "grid_x": 1,
                    "grid_y": 1,
                    "grid_w": 4,
                    "grid_h": 1,
                }
            ]
        },
        HTTP_IF_MATCH=str(dashboard["version"]),
    )
    assert layout_resp.status_code == 200, layout_resp.content
    layout_body = layout_resp.json()
    assert len(layout_body["widgets"]) == 1
    assert layout_body["version"] == dashboard["version"] + 1

    ui_dashboard = _call(client, "get", f"/api/v1/ui/dashboards/{dashboard['id']}")
    assert ui_dashboard.status_code == 200
    assert item["id"] in ui_dashboard.json()["items"]

    # ---------------------------------------------------------------- list create + reorder (edit)
    second_item = _call(
        client,
        "post",
        "/api/v1/catalog",
        {
            "title": "e2e-switch",
            "host": "e2e-switch.example.com",
            "connections": [{"protocol": "SSH", "port": 22}],
            "scope": "GLOBAL",
        },
    ).json()

    create_list = _call(
        client,
        "post",
        "/api/v1/lists",
        {"title": "E2E List", "scope": "GLOBAL", "item_ids": [item["id"], second_item["id"]]},
    )
    assert create_list.status_code == 201, create_list.content
    endpoint_list = create_list.json()
    assert endpoint_list["item_ids"] == [item["id"], second_item["id"]]

    reorder_resp = _call(
        client,
        "put",
        f"/api/v1/lists/{endpoint_list['id']}",
        {"title": "E2E List", "scope": "GLOBAL", "item_ids": [second_item["id"], item["id"]]},
        HTTP_IF_MATCH=str(endpoint_list["version"]),
    )
    assert reorder_resp.status_code == 200, reorder_resp.content
    assert reorder_resp.json()["item_ids"] == [second_item["id"], item["id"]]

    # ---------------------------------------------------------------- catalog edit
    patch_item = _call(client, "patch", f"/api/v1/catalog/{item['id']}", {"description": "edited in e2e"})
    assert patch_item.status_code == 200, patch_item.content
    assert patch_item.json()["description"] == "edited in e2e"

    # ---------------------------------------------------------------- admin action: create a team, edit a user
    create_team = _call(client, "post", "/api/v1/teams", {"code": _unique("E2E")[:12].upper(), "name": "E2E Team"})
    assert create_team.status_code == 201, create_team.content
    team = create_team.json()

    other_user = users_repo.create_user(
        mongo_db, username=_unique("e2e-member"), display_name="E2E Member", default_remote_user="e2emember"
    )
    patch_user = _call(
        client, "patch", f"/api/v1/users/{other_user.id}", {"team_ids": [team["id"]], "permissions": ["CAN_ADD_TEAM"]}
    )
    assert patch_user.status_code == 200, patch_user.content
    assert patch_user.json()["team_ids"] == [team["id"]]

    # ---------------------------------------------------------------- audit trail confirms the whole journey
    #
    # ``actor=`` scopes to this test's own real user: the shared test database accumulates audit
    # entries across the whole pytest session, and every mutation above (including the admin
    # actions) is attributed to this same real signed-in user, so this is a precise filter, not
    # an approximation.
    audit_resp = _call(client, "get", f"/api/v1/audit?limit=50&actor={username}")
    assert audit_resp.status_code == 200
    entries = audit_resp.json()["results"]
    by_action = {e["action"]: e for e in entries}

    assert by_action["auth.login"]["actor_username"] == username
    assert by_action["dashboard.create"]["target_id"] == dashboard["id"]
    assert by_action["catalog.create"]["actor_username"] == username
    assert by_action["dashboard.layout.update"]["target_id"] == dashboard["id"]
    assert by_action["list.create"]["target_id"] == endpoint_list["id"]
    assert by_action["list.update"]["target_id"] == endpoint_list["id"]
    assert by_action["catalog.update"]["target_id"] == item["id"]
    assert by_action["admin.team.create"]["target_id"] == team["id"]
    assert by_action["admin.user.update"]["target_id"] == other_user.id

    for entry in entries:
        assert entry["client_ip"]
        # auth.login's audit write (panic_server.auth.views.sign_in) does not carry a
        # request_id; every mutation does.
        assert entry["request_id"] or entry["action"] == "auth.login"

    # ---------------------------------------------------------------- sign out
    logout_resp = _call(client, "post", "/api/v1/auth/logout")
    assert logout_resp.status_code == 204
    assert _call(client, "get", "/api/v1/me").status_code == 401

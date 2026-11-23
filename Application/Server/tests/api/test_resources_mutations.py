"""Resources, mutations, concurrency, admin and diagnostics (API.md §4.3-§4.8, §6).

Covers the F1-F6 regression tests (ADR-0001), the orphan lifecycle, concurrent-edit semantics,
default-zone protections and the client-IP/zone diagnostics endpoint. Companion to
``test_e2e_workflow.py`` (the full sign-in-to-audit journey) and the extended mutation budgets in
``test_payload_budgets.py``.
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.test import Client

from panic_common.models import PermissionFlag, Protocol, ScopeType
from panic_server.context import SESSION_USER_KEY, SESSION_VIEW_AS_KEY
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _client_as(user_id: str | None) -> Client:
    client = Client()
    if user_id is not None:
        session = client.session
        session[SESSION_USER_KEY] = user_id
        session.save()
        client.cookies[django_settings.SESSION_COOKIE_NAME] = session.session_key
    return client


def _json(client: Client, method: str, path: str, body: dict[str, Any] | None = None, **extra: str) -> Any:
    kwargs: dict[str, Any] = dict(extra)
    if body is not None:
        kwargs["data"] = json.dumps(body)
        kwargs["content_type"] = "application/json"
    return getattr(client, method)(path, **kwargs)


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Any) -> None:
    zones_repo.ensure_default_zone(mongo_db)


@pytest.fixture
def plain(mongo_db: Any) -> Any:
    username = _unique("mut-plain")
    return users_repo.create_user(mongo_db, username=username, display_name="Mut Plain", default_remote_user=username)


@pytest.fixture
def admin(mongo_db: Any) -> Any:
    username = _unique("mut-admin")
    return users_repo.create_user(
        mongo_db,
        username=username,
        display_name="Mut Admin",
        default_remote_user=username,
        permissions=[str(PermissionFlag.GLOBAL_ADMIN)],
    )


# ============================================================================ F1: users RBAC


def test_f1_only_global_admin_may_patch_user_permissions(mongo_db: Any, plain: Any, admin: Any) -> None:
    target = users_repo.create_user(
        mongo_db, username=_unique("mut-target"), display_name="Target", default_remote_user="target"
    )

    plain_resp = _json(_client_as(plain.id), "patch", f"/api/v1/users/{target.id}", {"permissions": ["CAN_ADD_TEAM"]})
    assert plain_resp.status_code == 403
    assert plain_resp.json()["error_code"] == "PERMISSION_DENIED"

    admin_resp = _json(_client_as(admin.id), "patch", f"/api/v1/users/{target.id}", {"permissions": ["CAN_ADD_TEAM"]})
    assert admin_resp.status_code == 200
    assert admin_resp.json()["permissions"] == ["CAN_ADD_TEAM"]


def test_f1_last_enabled_admin_cannot_be_demoted_or_disabled(mongo_db: Any, admin: Any) -> None:
    # The shared test database may carry other admins from earlier tests in this session; force
    # ``admin`` to be the *only* enabled GLOBAL_ADMIN so this test's premise actually holds.
    for other in users_repo.list_users(mongo_db, permission=str(PermissionFlag.GLOBAL_ADMIN), disabled=False):
        if other.id != admin.id:
            users_repo.update_user(mongo_db, other.id, other.version, disabled=True)

    client = _client_as(admin.id)
    resp = _json(client, "patch", f"/api/v1/users/{admin.id}", {"disabled": True})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "PROTECTED_RESOURCE"

    resp2 = _json(client, "patch", f"/api/v1/users/{admin.id}", {"permissions": []})
    assert resp2.status_code == 409
    assert resp2.json()["error_code"] == "PROTECTED_RESOURCE"


def test_disabling_user_flushes_sessions_and_recomputes_orphans(mongo_db: Any, admin: Any) -> None:
    victim = users_repo.create_user(
        mongo_db, username=_unique("mut-victim"), display_name="Victim", default_remote_user="victim"
    )
    item = catalog_repo.create_catalog_item(
        mongo_db,
        title="victim-personal",
        protocol=str(Protocol.SSH),
        host="victim.example.com",
        normalized_key=_unique("ssh://victim"),
        created_by=victim.username,
        scope=str(ScopeType.PERSONAL),
        owner_usernames=[victim.username],
    )
    victim_client = _client_as(victim.id)
    assert victim_client.get("/api/v1/me").status_code == 200

    resp = _json(_client_as(admin.id), "patch", f"/api/v1/users/{victim.id}", {"disabled": True})
    assert resp.status_code == 200

    # Session flushed: the same session cookie no longer identifies anyone.
    assert victim_client.get("/api/v1/me").status_code == 401

    refreshed = catalog_repo.get_catalog_item(mongo_db, item.id)
    assert refreshed.orphaned is True


# ============================================================================ F2: audit admin-only


def test_f2_audit_is_admin_only(plain: Any, admin: Any) -> None:
    assert _client_as(plain.id).get("/api/v1/audit").status_code == 403
    resp = _client_as(admin.id).get("/api/v1/audit")
    assert resp.status_code == 200
    assert "results" in resp.json()


# ============================================================================ F3


def test_f3_rdp_download_still_requires_visibility(mongo_db: Any, plain: Any) -> None:
    rdp_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="f3-rdp",
        protocol=str(Protocol.RDP),
        host="f3.example.com",
        port=3389,
        normalized_key=_unique("rdp://f3"),
        created_by="system",
        scope=str(ScopeType.PERSONAL),
        owner_usernames=["someone-else"],
    )
    resp = _client_as(plain.id).get(f"/api/v1/launch/rdp/{rdp_item.id}.rdp")
    assert (
        resp.status_code == 404
    )  # covered fully by tests/api/test_ui_endpoints.py; re-asserted here for F1-F6 completeness.


# ============================================================================ F4: ownership, not just scope permission


def test_f4_stranger_cannot_even_see_a_team_item_outside_their_teams(mongo_db: Any) -> None:
    team_a = teams_repo.create_team(mongo_db, code=_unique("TA"), name="Team A")
    team_b = teams_repo.create_team(mongo_db, code=_unique("TB"), name="Team B")
    stranger = users_repo.create_user(
        mongo_db,
        username=_unique("mut-stranger"),
        display_name="Stranger",
        default_remote_user="stranger",
        team_ids=[team_a.id],
        permissions=[str(PermissionFlag.CAN_ADD_TEAM)],
    )
    item = catalog_repo.create_catalog_item(
        mongo_db,
        title="team-b-only",
        protocol=str(Protocol.SSH),
        host="teamb.example.com",
        normalized_key=_unique("ssh://teamb"),
        created_by="system",
        scope=str(ScopeType.TEAM),
        team_ids=[team_b.id],
    )
    client = _client_as(stranger.id)
    # Invisible (not a member of team_b, and CAN_ADD_TEAM alone doesn't grant visibility): 404,
    # never 403 (AR-2.7) -- F4: scope permission alone must not let a non-member edit *any*
    # team's resources; they cannot even see one outside their teams.
    assert client.get(f"/api/v1/catalog/{item.id}").status_code == 404
    resp = _json(client, "patch", f"/api/v1/catalog/{item.id}", {"title": "hijacked"})
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


def test_f4_stranger_cannot_see_another_users_personal_item(mongo_db: Any, plain: Any) -> None:
    item = catalog_repo.create_catalog_item(
        mongo_db,
        title="someone-elses",
        protocol=str(Protocol.SSH),
        host="personal.example.com",
        normalized_key=_unique("ssh://personal"),
        created_by="system",
        scope=str(ScopeType.PERSONAL),
        owner_usernames=["someone-else"],
    )
    client = _client_as(plain.id)
    assert client.get(f"/api/v1/catalog/{item.id}").status_code == 404
    resp = _json(client, "delete", f"/api/v1/catalog/{item.id}")
    assert resp.status_code == 404


def test_f4_visible_team_member_without_permission_gets_403_not_404(mongo_db: Any) -> None:
    """The genuine 403 case: visible (team member) but no CAN_ADD_TEAM -> PERMISSION_DENIED."""
    team = teams_repo.create_team(mongo_db, code=_unique("TC"), name="Team C")
    member_no_perm = users_repo.create_user(
        mongo_db,
        username=_unique("mut-member"),
        display_name="Member",
        default_remote_user="member",
        team_ids=[team.id],
    )
    item = catalog_repo.create_catalog_item(
        mongo_db,
        title="team-c-item",
        protocol=str(Protocol.SSH),
        host="teamc.example.com",
        normalized_key=_unique("ssh://teamc"),
        created_by="system",
        scope=str(ScopeType.TEAM),
        team_ids=[team.id],
    )
    client = _client_as(member_no_perm.id)
    assert client.get(f"/api/v1/catalog/{item.id}").status_code == 200  # visible: shares the team
    resp = _json(client, "patch", f"/api/v1/catalog/{item.id}", {"title": "nope"})
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "PERMISSION_DENIED"


# ============================================================================ F5: duplicate / test-ip leak


def test_f5_duplicate_check_ignores_an_invisible_match(mongo_db: Any, plain: Any) -> None:
    key = _unique("ssh://dup-target.example.com:22")
    catalog_repo.create_catalog_item(
        mongo_db,
        title="someone-elses-dup",
        protocol=str(Protocol.SSH),
        host="dup-target.example.com",
        port=22,
        normalized_key=key,
        created_by="system",
        scope=str(ScopeType.PERSONAL),
        owner_usernames=["someone-else"],
    )
    resp = _json(
        _client_as(plain.id),
        "post",
        "/api/v1/catalog",
        {
            "title": "my-own-dup",
            "protocol": "SSH",
            "host": "dup-target.example.com",
            "port": 22,
            "scope": "PERSONAL",
        },
    )
    assert resp.status_code == 201, resp.content


def test_f5_test_ip_is_admin_only_and_returns_counts_not_items(mongo_db: Any, plain: Any, admin: Any) -> None:
    catalog_repo.create_catalog_item(
        mongo_db,
        title="reachable-item",
        protocol=str(Protocol.SSH),
        host="reachable.example.com",
        normalized_key=_unique("ssh://reachable"),
        created_by="system",
    )
    plain_resp = _json(_client_as(plain.id), "post", "/api/v1/zones/test-ip", {"ip": "203.0.113.5"})
    assert plain_resp.status_code == 403

    admin_resp = _json(_client_as(admin.id), "post", "/api/v1/zones/test-ip", {"ip": "203.0.113.5"})
    assert admin_resp.status_code == 200
    body = admin_resp.json()
    assert "reachable_count" in body and "blocked_count" in body
    assert "items" not in body
    assert "items" not in body["resolution"]
    assert body["resolution"]["zone_source"] == "DEFAULT"


# ============================================================================ F6: list item scope/visibility


def test_f6_list_save_rejects_invisible_item_and_does_not_mutate(mongo_db: Any, plain: Any) -> None:
    invisible_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="invisible-personal",
        protocol=str(Protocol.SSH),
        host="invisible.example.com",
        normalized_key=_unique("ssh://invisible"),
        created_by="system",
        scope=str(ScopeType.PERSONAL),
        owner_usernames=["someone-else"],
    )
    lst = lists_repo.create_list(
        mongo_db,
        title="F6 List",
        created_by=plain.username,
        scope="PERSONAL",
        owner_usernames=[plain.username],
        item_ids=[],
    )
    client = _client_as(plain.id)
    resp = _json(
        client,
        "put",
        f"/api/v1/lists/{lst.id}",
        {"title": "F6 List", "scope": "PERSONAL", "item_ids": [invisible_item.id]},
        HTTP_IF_MATCH=str(lst.version),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] in {"VALIDATION_ERROR", "SCOPE_MISMATCH"}

    unchanged = lists_repo.get_list(mongo_db, lst.id)
    assert unchanged.item_ids == []
    assert unchanged.version == lst.version


def test_f6_list_save_rejects_wrong_scope_item(mongo_db: Any, plain: Any) -> None:
    global_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="global-item",
        protocol=str(Protocol.SSH),
        host="global.example.com",
        normalized_key=_unique("ssh://global"),
        created_by="system",
        scope=str(ScopeType.GLOBAL),
    )
    lst = lists_repo.create_list(
        mongo_db,
        title="F6 Team List",
        created_by=plain.username,
        scope="PERSONAL",
        owner_usernames=[plain.username],
        item_ids=[],
    )
    client = _client_as(plain.id)
    resp = _json(
        client,
        "put",
        f"/api/v1/lists/{lst.id}",
        {"title": "F6 Team List", "scope": "PERSONAL", "item_ids": [global_item.id]},
        HTTP_IF_MATCH=str(lst.version),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "SCOPE_MISMATCH"


# ============================================================================ If-Match / 428 / 409


def test_dashboard_patch_requires_if_match(mongo_db: Any, plain: Any) -> None:
    dashboard = dashboards_repo.create_dashboard(
        mongo_db, title="IfMatch Dash", created_by=plain.username, scope="PERSONAL", owner_usernames=[plain.username]
    )
    client = _client_as(plain.id)
    resp = _json(client, "patch", f"/api/v1/dashboards/{dashboard.id}", {"title": "New"})
    assert resp.status_code == 428
    assert resp.json()["error_code"] == "PRECONDITION_REQUIRED"


def test_dashboard_icon_create_patch_and_menu(mongo_db: Any, plain: Any) -> None:
    client = _client_as(plain.id)
    bad = _json(client, "post", "/api/v1/dashboards", {"title": "Bad Icon", "scope": "PERSONAL", "icon": "x y"})
    assert bad.status_code == 400 and "icon" in bad.json()["fields"]
    plain_default = _json(client, "post", "/api/v1/dashboards", {"title": "No Icon", "scope": "PERSONAL"})
    assert plain_default.json()["icon"] == "dashboard"
    made = _json(client, "post", "/api/v1/dashboards", {"title": "Routers", "scope": "PERSONAL", "icon": "router"})
    assert made.status_code == 201 and made.json()["icon"] == "router"
    patched = _json(
        client,
        "patch",
        f"/api/v1/dashboards/{made.json()['id']}",
        {"icon": "dns"},
        HTTP_IF_MATCH=str(made.json()["version"]),
    )
    assert patched.status_code == 200
    nav = client.get("/api/v1/ui/bootstrap").json()["nav"]["dashboards"]
    assert {d["id"]: d["icon"] for d in nav}[made.json()["id"]] == "dns"


def test_dashboard_layout_rejects_duplicate_targets(mongo_db: Any, plain: Any) -> None:
    dashboard = dashboards_repo.create_dashboard(
        mongo_db, title="Dup Dash", created_by=plain.username, scope="PERSONAL", owner_usernames=[plain.username]
    )
    lst = lists_repo.create_list(
        mongo_db,
        title="Dup List",
        created_by=plain.username,
        scope="PERSONAL",
        owner_usernames=[plain.username],
        item_ids=[],
    )
    widget = {"widget_type": "LIST", "list_id": lst.id, "grid_x": 1, "grid_y": 1, "grid_w": 6, "grid_h": 2}
    client = _client_as(plain.id)
    resp = _json(
        client,
        "put",
        f"/api/v1/dashboards/{dashboard.id}/layout",
        {"widgets": [widget, {**widget, "grid_y": 3}]},
        HTTP_IF_MATCH=str(dashboard.version),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"
    once = _json(
        client,
        "put",
        f"/api/v1/dashboards/{dashboard.id}/layout",
        {"widgets": [widget]},
        HTTP_IF_MATCH=str(dashboard.version),
    )
    assert once.status_code == 200


def test_list_put_stale_if_match_returns_409_with_current_version(mongo_db: Any, plain: Any) -> None:
    lst = lists_repo.create_list(
        mongo_db,
        title="Stale List",
        created_by=plain.username,
        scope="PERSONAL",
        owner_usernames=[plain.username],
        item_ids=[],
    )
    client = _client_as(plain.id)
    first = _json(
        client,
        "put",
        f"/api/v1/lists/{lst.id}",
        {"title": "v2", "scope": "PERSONAL", "item_ids": []},
        HTTP_IF_MATCH=str(lst.version),
    )
    assert first.status_code == 200
    assert first.json()["version"] == lst.version + 1

    stale = _json(
        client,
        "put",
        f"/api/v1/lists/{lst.id}",
        {"title": "v3", "scope": "PERSONAL", "item_ids": []},
        HTTP_IF_MATCH=str(lst.version),
    )
    assert stale.status_code == 409
    body = stale.json()
    assert body["error_code"] == "VERSION_CONFLICT"
    assert body["current_version"] == lst.version + 1


def test_concurrent_dashboard_patch_exactly_one_winner(mongo_db: Any, plain: Any) -> None:
    dashboard = dashboards_repo.create_dashboard(
        mongo_db, title="Race Dash", created_by=plain.username, scope="PERSONAL", owner_usernames=[plain.username]
    )
    starting_version = dashboard.version
    results: list[Any] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def attempt(title: str) -> None:
        barrier.wait()
        client = _client_as(plain.id)
        resp = _json(
            client, "patch", f"/api/v1/dashboards/{dashboard.id}", {"title": title}, HTTP_IF_MATCH=str(starting_version)
        )
        with results_lock:
            results.append(resp)

    threads = [threading.Thread(target=attempt, args=(f"race-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 409]
    winner = next(r for r in results if r.status_code == 200)
    loser = next(r for r in results if r.status_code == 409)
    assert winner.json()["version"] == starting_version + 1
    assert loser.json()["current_version"] == starting_version + 1


# ============================================================================ Orphan lifecycle


def test_orphan_lifecycle(mongo_db: Any, admin: Any) -> None:
    team = teams_repo.create_team(mongo_db, code=_unique("ORPH"), name="Orphan Team")
    member = users_repo.create_user(
        mongo_db,
        username=_unique("mut-orphmember"),
        display_name="Orph Member",
        default_remote_user="orphmember",
        team_ids=[team.id],
    )
    item = catalog_repo.create_catalog_item(
        mongo_db,
        title="orphan-candidate",
        protocol=str(Protocol.SSH),
        host="orphan.example.com",
        normalized_key=_unique("ssh://orphan"),
        created_by="system",
        scope=str(ScopeType.TEAM),
        team_ids=[team.id],
    )
    second_item = catalog_repo.create_catalog_item(
        mongo_db,
        title="orphan-candidate-2",
        protocol=str(Protocol.SSH),
        host="orphan2.example.com",
        normalized_key=_unique("ssh://orphan2"),
        created_by="system",
        scope=str(ScopeType.TEAM),
        team_ids=[team.id],
    )

    admin_client = _client_as(admin.id)
    del_resp = _json(admin_client, "delete", f"/api/v1/teams/{team.id}", HTTP_IF_MATCH=str(team.version))
    assert del_resp.status_code == 200
    assert del_resp.json()["orphaned"]["catalog"] >= 2

    orphaned_item = catalog_repo.get_catalog_item(mongo_db, item.id)
    assert orphaned_item.orphaned is True
    assert orphaned_item.team_ids == []

    # Invisible to a plain member (membership was pulled along with the team's deletion).
    member_client = _client_as(member.id)
    assert member_client.get(f"/api/v1/catalog/{item.id}").status_code == 404
    listing = member_client.get("/api/v1/catalog").json()
    assert item.id not in {row["id"] for row in listing["results"]}

    # Visible to admin, with the orphan flag; editing is refused.
    admin_get = admin_client.get(f"/api/v1/catalog/{item.id}")
    assert admin_get.status_code == 200
    assert admin_get.json()["orphaned"] is True
    edit_resp = _json(admin_client, "patch", f"/api/v1/catalog/{item.id}", {"title": "nope"})
    assert edit_resp.status_code == 403
    assert edit_resp.json()["error_code"] == "ORPHANED_RESOURCE"

    # Admin deletes an orphan directly (the one explicit DELETE exception).
    current = catalog_repo.get_catalog_item(mongo_db, second_item.id)
    delete_orphan_resp = _json(
        admin_client, "delete", f"/api/v1/catalog/{second_item.id}", HTTP_IF_MATCH=str(current.version)
    )
    assert delete_orphan_resp.status_code == 204

    # Assign-to-user: becomes PERSONAL for an enabled user.
    assign_resp = _json(
        admin_client, "post", f"/api/v1/admin/orphans/catalog/{item.id}/assign", {"username": member.username}
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["scope"] == "PERSONAL"

    reassigned = catalog_repo.get_catalog_item(mongo_db, item.id)
    assert reassigned.orphaned is False
    assert reassigned.owner_usernames == [member.username]

    # The new owner can now delete their own resource.
    final_delete = _json(member_client, "delete", f"/api/v1/catalog/{item.id}", HTTP_IF_MATCH=str(reassigned.version))
    assert final_delete.status_code == 204


# ============================================================================ Default zone protections


def test_default_zone_cannot_be_deleted_or_renamed(mongo_db: Any, admin: Any) -> None:
    default_zone = zones_repo.get_zone(mongo_db, zones_repo.DEFAULT_ZONE_ID)
    client = _client_as(admin.id)

    rename_resp = _json(
        client,
        "patch",
        f"/api/v1/zones/{default_zone.id}",
        {"name": "Not Default"},
        HTTP_IF_MATCH=str(default_zone.version),
    )
    assert rename_resp.status_code == 400
    assert rename_resp.json()["error_code"] == "VALIDATION_ERROR"

    add_cidr_resp = _json(
        client,
        "patch",
        f"/api/v1/zones/{default_zone.id}",
        {"cidrs": ["10.0.0.0/8"]},
        HTTP_IF_MATCH=str(default_zone.version),
    )
    assert add_cidr_resp.status_code == 400

    describe_resp = _json(
        client,
        "patch",
        f"/api/v1/zones/{default_zone.id}",
        {"description": "updated description"},
        HTTP_IF_MATCH=str(default_zone.version),
    )
    assert describe_resp.status_code == 200
    assert describe_resp.json()["description"] == "updated description"

    delete_resp = _json(client, "delete", f"/api/v1/zones/{default_zone.id}", HTTP_IF_MATCH=str(default_zone.version))
    assert delete_resp.status_code == 409
    assert delete_resp.json()["error_code"] == "PROTECTED_RESOURCE"


def test_last_site_cannot_be_deleted(mongo_db: Any, admin: Any) -> None:
    for s in sites_repo.list_sites(mongo_db):
        sites_repo.delete_site(mongo_db, s.id, s.version)
    site = sites_repo.create_site(mongo_db, code=_unique("S")[-6:].upper(), name="Only Site")
    resp = _json(_client_as(admin.id), "delete", f"/api/v1/sites/{site.id}", HTTP_IF_MATCH=str(site.version))
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "PROTECTED_RESOURCE"


# ============================================================================ View As


def test_view_as_read_only_and_exit(mongo_db: Any, admin: Any, plain: Any) -> None:
    admin_client = _client_as(admin.id)
    start_resp = _json(admin_client, "put", "/api/v1/admin/view-as", {"user_id": plain.id})
    assert start_resp.status_code == 200
    assert start_resp.json()["me"]["username"] == plain.username

    # Writes under /me are refused while View As is active.
    mutate_resp = _json(admin_client, "patch", "/api/v1/me", {"display_name": "Should Not Apply"})
    assert mutate_resp.status_code == 403
    assert mutate_resp.json()["error_code"] == "VIEW_AS_READ_ONLY"

    exit_resp = _json(admin_client, "delete", "/api/v1/admin/view-as")
    assert exit_resp.status_code == 200
    assert exit_resp.json()["me"]["username"] == admin.username

    # Now writes work again, on the real admin.
    resume_resp = _json(admin_client, "patch", "/api/v1/me", {"display_name": "Back To Admin"})
    assert resume_resp.status_code == 200


def test_view_as_zone_with_and_without_user(mongo_db: Any, admin: Any, plain: Any) -> None:
    zone = zones_repo.create_zone(mongo_db, name=_unique("View As Zone"), cidrs=["192.0.2.128/25"])
    client = _client_as(admin.id)

    assert _json(client, "put", "/api/v1/admin/view-as", {}).status_code == 400  # needs a user or a zone

    # Zone only: still the admin, but from that zone; mutations are refused.
    only_zone = _json(client, "put", "/api/v1/admin/view-as", {"zone_id": zone.id})
    assert only_zone.status_code == 200
    body = only_zone.json()
    assert body["me"]["username"] == admin.username
    assert body["client"]["zone"]["id"] == zone.id and body["client"]["zone_source"] == "VIEW_AS"
    assert body["view_as"] is not None
    assert _json(client, "patch", "/api/v1/me", {"display_name": "x"}).status_code == 403

    # User and zone together.
    both = _json(client, "put", "/api/v1/admin/view-as", {"user_id": plain.id, "zone_id": zone.id}).json()
    assert both["me"]["username"] == plain.username and both["client"]["zone"]["id"] == zone.id

    # Exit clears both.
    out = _json(client, "delete", "/api/v1/admin/view-as").json()
    assert out["me"]["username"] == admin.username and out["client"]["zone_source"] != "VIEW_AS"
    assert out["view_as"] is None


def test_view_as_exit_allowed_even_when_viewing_as_non_admin(mongo_db: Any, admin: Any, plain: Any) -> None:
    """IsRealGlobalAdmin, not IsGlobalAdmin, must gate the DELETE too."""
    client = _client_as(admin.id)
    session = client.session
    session[SESSION_VIEW_AS_KEY] = plain.id
    session.save()
    resp = _json(client, "delete", "/api/v1/admin/view-as")
    assert resp.status_code == 200


# ============================================================================ Client-IP diagnostics


def test_client_ip_diagnostics_admin_only(plain: Any, admin: Any) -> None:
    assert _client_as(plain.id).get("/api/v1/admin/client-ip").status_code == 403
    resp = _client_as(admin.id).get("/api/v1/admin/client-ip")
    assert resp.status_code == 200
    body = resp.json()
    assert {
        "remote_addr",
        "policy",
        "hops",
        "decision",
        "client_ip",
        "zone",
        "zone_source",
        "candidates",
    } <= body.keys()


def test_untrusted_peer_resolves_to_default_zone(admin: Any) -> None:
    resp = _client_as(admin.id).get("/api/v1/admin/client-ip", REMOTE_ADDR="203.0.113.77")
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "UNTRUSTED_PEER"
    assert body["zone"]["id"] == zones_repo.DEFAULT_ZONE_ID
    assert body["zone_source"] == "DEFAULT"


def test_unmatched_ip_resolves_to_default_zone(mongo_db: Any, admin: Any) -> None:
    zones_repo.create_zone(mongo_db, name=_unique("Narrow Zone"), cidrs=["10.0.0.0/24"])
    resp = _client_as(admin.id).get(
        "/api/v1/admin/client-ip", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="198.51.100.9"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "FIRST_UNTRUSTED_HOP"
    assert body["client_ip"] == "198.51.100.9"
    assert body["zone"]["id"] == zones_repo.DEFAULT_ZONE_ID
    assert body["zone_source"] == "DEFAULT"


# ============================================================================ Export


def test_export_is_admin_only_and_audited(mongo_db: Any, plain: Any, admin: Any) -> None:
    assert _client_as(plain.id).get("/api/v1/export").status_code == 403
    resp = _client_as(admin.id).get("/api/v1/export")
    assert resp.status_code == 200
    doc = json.loads(resp.content)
    assert doc["format"] == "panic-export"

    audit_resp = _client_as(admin.id).get("/api/v1/audit?action=admin.export")
    assert audit_resp.status_code == 200
    assert any(e["action"] == "admin.export" for e in audit_resp.json()["results"])


# ============================================================================ Settings
#
# ``system_settings`` is a fixed-id singleton (``_id: "system"``), unlike every other fixture in
# this file -- it is not per-test-uniquified, so touching it leaks across tests that share the
# session-scoped ``mongo_db`` (e.g. ``tests/store/test_repos_users_settings_audit.py``'s own
# ``ensure_system_settings`` idempotency test assumes it is the first to ever create the
# document). ``_clean_system_settings`` resets it to "does not exist yet" before *and* after, so
# this file is a good citizen regardless of collection order.


@pytest.fixture
def _clean_system_settings(mongo_db: Any) -> Any:
    settings_repo.delete_system_settings(mongo_db)
    yield
    settings_repo.delete_system_settings(mongo_db)


@pytest.mark.usefixtures("_clean_system_settings")
def test_settings_get_any_user_patch_admin_only(mongo_db: Any, plain: Any, admin: Any) -> None:
    # Production always has this (panic_migrate step 1, like the Default zone); a fresh test
    # database does not, so this mirrors the _default_zone fixture's role for settings.
    settings_repo.ensure_system_settings(mongo_db, default_global_dashboard_id="", updated_by="system")
    dashboard = dashboards_repo.create_dashboard(mongo_db, title="Settings Target", created_by="system", scope="GLOBAL")

    get_resp = _client_as(plain.id).get("/api/v1/settings")
    assert get_resp.status_code == 200
    version = get_resp.json()["version"]

    plain_patch = _json(
        _client_as(plain.id),
        "patch",
        "/api/v1/settings",
        {"default_global_dashboard_id": dashboard.id},
        HTTP_IF_MATCH=str(version),
    )
    assert plain_patch.status_code == 403

    admin_patch = _json(
        _client_as(admin.id),
        "patch",
        "/api/v1/settings",
        {"default_global_dashboard_id": dashboard.id},
        HTTP_IF_MATCH=str(version),
    )
    assert admin_patch.status_code == 200
    assert admin_patch.json()["default_global_dashboard"]["id"] == dashboard.id


@pytest.mark.usefixtures("_clean_system_settings")
def test_settings_patch_rejects_non_global_dashboard(mongo_db: Any, admin: Any) -> None:
    settings_repo.ensure_system_settings(mongo_db, default_global_dashboard_id="", updated_by="system")
    team_dashboard = dashboards_repo.create_dashboard(
        mongo_db, title="Team Dashboard", created_by="system", scope="TEAM", team_ids=["some-team"]
    )
    version = _client_as(admin.id).get("/api/v1/settings").json()["version"]
    resp = _json(
        _client_as(admin.id),
        "patch",
        "/api/v1/settings",
        {"default_global_dashboard_id": team_dashboard.id},
        HTTP_IF_MATCH=str(version),
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_settings_ssh_uri_handler_switch_and_scheme(mongo_db: Any, admin: Any) -> None:
    from panic_common.models import CatalogItem
    from panic_server.services.launch import build_item_view

    settings_repo.ensure_system_settings(mongo_db, default_global_dashboard_id="", updated_by="system")
    client = _client_as(admin.id)
    item = CatalogItem(
        id="cat-uri",
        title="r1",
        protocol=Protocol.SSH,
        host="r1.example.com",
        port=2222,
        site="S1",
        normalized_key="ssh://r1.example.com:2222",
    )

    def uri() -> str | None:
        return build_item_view(item, caller=admin, active_zone=None, zones_by_id={})["launch"].get("uri")

    def patch(body: dict[str, Any]) -> Any:
        version = client.get("/api/v1/settings").json()["version"]
        return _json(client, "patch", "/api/v1/settings", body, HTTP_IF_MATCH=str(version))

    bad = patch({"ssh_uri_scheme": "https"})
    assert bad.status_code == 400 and "ssh_uri_scheme" in bad.json()["fields"]
    on = patch({"ssh_uri_enabled": True, "ssh_uri_scheme": "corp-ssh"})
    assert on.status_code == 200 and on.json()["ssh_uri_scheme"] == "corp-ssh"
    assert uri() == f"corp-ssh://{admin.default_remote_user}@r1.example.com:2222"
    off = patch({"ssh_uri_enabled": False})
    assert off.status_code == 200 and off.json()["ssh_uri_enabled"] is False
    assert uri() is None  # disabled: no URI at all, so no "open with system handler" anywhere
    # Leave no settings document behind: later store tests create it fresh at version 1.
    settings_repo.delete_system_settings(mongo_db)
    settings_repo.invalidate_ssh_uri_cache()


# ============================================================================ Sites/teams/users admin CRUD smoke


def test_site_crud(mongo_db: Any, admin: Any) -> None:
    client = _client_as(admin.id)
    create_resp = _json(client, "post", "/api/v1/sites", {"code": _unique("S")[-8:].upper(), "name": "New Site"})
    assert create_resp.status_code == 201
    site = create_resp.json()

    patch_resp = _json(client, "patch", f"/api/v1/sites/{site['id']}", {"name": "Renamed Site"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Renamed Site"


def test_users_crud_and_team_membership_via_patch_only(mongo_db: Any, admin: Any) -> None:
    client = _client_as(admin.id)
    team_resp = _json(client, "post", "/api/v1/teams", {"code": _unique("UT")[:12].upper(), "name": "User Team"})
    assert team_resp.status_code == 201
    team = team_resp.json()

    create_resp = _json(
        client, "post", "/api/v1/users", {"username": _unique("crud-user"), "display_name": "Crud User"}
    )
    assert create_resp.status_code == 201
    user = create_resp.json()
    assert user["team_ids"] == []

    patch_resp = _json(client, "patch", f"/api/v1/users/{user['id']}", {"team_ids": [team["id"]]})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["team_ids"] == [team["id"]]

    members_resp = client.get(f"/api/v1/teams/{team['id']}/members")
    assert members_resp.status_code == 200
    assert user["id"] in {m["id"] for m in members_resp.json()["results"]}

    detail_resp = client.get(f"/api/v1/users/{user['id']}")
    assert detail_resp.status_code == 200
    assert "owned_counts" in detail_resp.json()

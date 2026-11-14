"""Integration and unit tests for panic_server (HTML views, REST APIs, .rdp generator, lists, teams, zones, RBAC)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from panic_server.state import (
    DASH_GLOBAL_NETOPS_ID,
    DASH_GLOBAL_NOC_ID,
    DASH_PERSONAL_BENCH_ID,
    DASH_TEAM_COMPUTE_ID,
    DASH_TEAM_SECOPS_ID,
    STORE,
)


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    STORE.reset()


def test_health_version_and_metrics_endpoints() -> None:
    client = Client()
    h = client.get("/api/v1/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"
    assert "X-Request-ID" in h.headers

    v = client.get("/api/v1/version")
    assert v.status_code == 200
    assert v.json()["name"] == "panic-server"

    m = client.get("/metrics")
    assert m.status_code == 200
    assert b"panic_http_requests_total" in m.content


def test_server_rendered_html_views() -> None:
    client = Client()
    for route in (
        "/",
        "/dashboard",
        f"/dashboard/{DASH_GLOBAL_NETOPS_ID}",
        f"/dashboard/{DASH_GLOBAL_NETOPS_ID}/edit",
        "/lists",
        "/catalog",
        "/sites",
        "/teams",
        "/zones",
        "/rbac",
        "/settings",
        "/profile",
        "/audit",
    ):
        resp = client.get(route)
        assert resp.status_code == 200
        assert b"panic-initial-state" in resp.content
        assert b"Portal for Accessing Networks, Infrastructure, and Compute" in resp.content


def test_dynamic_rdp_download_and_sanitization() -> None:
    client = Client()
    resp = client.get("/api/v1/launch/rdp/cat-rdp-bastion-01.rdp")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("application/x-rdp")
    assert "attachment; filename=" in resp["Content-Disposition"]
    body = resp.content.decode("utf-8")
    assert "full address:s:bastion01.ops.example.com:3389\r\n" in body
    assert "username:s:OPS\\joperator\r\n" in body


def test_simulator_switches_zone_ip_and_active_user() -> None:
    client = Client()
    resp = client.post(
        "/api/v1/simulator",
        data=json.dumps({"simulated_ip": "10.20.100.15", "active_user_id": "usr-standard"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["simulation"]["simulated_ip"] == "10.20.100.15"
    assert data["simulation"]["resolved_zone"]["id"] == "zone-dmz"
    assert data["user"]["username"] == "alex.chen"


def test_catalog_item_creation_and_rbac_enforcement() -> None:
    client = Client()
    # 1. Credential hygiene rejection
    bad_resp = client.post(
        "/api/v1/catalog",
        data=json.dumps(
            {
                "action": "create",
                "title": "Bad Router",
                "protocol": "SSH",
                "host": "root:secret123@router.ops.example.net",
                "port": 22,
                "scope": "GLOBAL",
            }
        ),
        content_type="application/json",
    )
    assert bad_resp.status_code == 400
    assert bad_resp.json()["error_code"] == "CREDENTIAL_HYGIENE_VIOLATION"

    # 2. Switch to alex.chen (usr-standard: Personal scope only) and verify GLOBAL item creation is blocked by RBAC
    client.post(
        "/api/v1/simulator",
        data=json.dumps({"active_user_id": "usr-standard"}),
        content_type="application/json",
    )
    denied_resp = client.post(
        "/api/v1/catalog",
        data=json.dumps(
            {
                "action": "create",
                "title": "Unauthorized Global Item",
                "protocol": "SSH",
                "host": "rtr99.network.example.com",
                "port": 22,
                "site": "2SYA",
                "scope": "GLOBAL",
            }
        ),
        content_type="application/json",
    )
    assert denied_resp.status_code == 403
    assert denied_resp.json()["error_code"] == "PERMISSION_DENIED"

    # 3. Personal scope item creation succeeds for alex.chen
    ok_resp = client.post(
        "/api/v1/catalog",
        data=json.dumps(
            {
                "action": "create",
                "title": "My Personal Switch",
                "protocol": "SSH",
                "host": "sw-personal.lab.example.com",
                "port": 22,
                "site": "2SYA",
                "scope": "PERSONAL",
                "zone_ids": ["zone-dmz"],
            }
        ),
        content_type="application/json",
    )
    assert ok_resp.status_code == 200
    created_id = ok_resp.json()["created_item_id"]
    created_item = next(c for c in ok_resp.json()["state"]["catalog"] if c["id"] == created_id)
    assert created_item["scope"] == "PERSONAL"
    assert created_item["site"] == "2SYA"


def test_lists_enforce_same_scope_items_and_dashboard_host_or_list_widgets() -> None:
    client = Client()
    # Try adding a PERSONAL catalog item ('cat-pers-lab-rtr') into a GLOBAL list -> must fail with SCOPE_MISMATCH
    mismatch_resp = client.post(
        "/api/v1/lists",
        data=json.dumps(
            {
                "action": "save",
                "title": "Invalid Mixed Scope List",
                "scope": "GLOBAL",
                "item_ids": ["cat-rtr-2sya-01", "cat-pers-lab-rtr"],
            }
        ),
        content_type="application/json",
    )
    assert mismatch_resp.status_code == 400
    assert mismatch_resp.json()["error_code"] == "SCOPE_MISMATCH"

    # Creating a GLOBAL list with only GLOBAL items succeeds
    valid_list_resp = client.post(
        "/api/v1/lists",
        data=json.dumps(
            {
                "action": "save",
                "id": "list-core-global-test",
                "title": "Core Routers Global",
                "scope": "GLOBAL",
                "item_ids": ["cat-rtr-2sya-01", "cat-rtr-3mel-02"],
            }
        ),
        content_type="application/json",
    )
    assert valid_list_resp.status_code == 200
    created_list = next(item for item in valid_list_resp.json()["lists"] if item["id"] == "list-core-global-test")
    assert created_list["scope"] == "GLOBAL"

    # Create a new dashboard and save layout with HOST and LIST widgets
    dash_create = client.post(
        "/api/v1/dashboards",
        data=json.dumps(
            {
                "action": "create",
                "title": "Custom Ops Grid",
                "description": "Host and List widgets",
                "scope": "GLOBAL",
            }
        ),
        content_type="application/json",
    )
    assert dash_create.status_code == 200
    dash_id = dash_create.json()["created_dashboard_id"]

    layout_resp = client.put(
        f"/api/v1/dashboards/{dash_id}/layout",
        data=json.dumps(
            {
                "title": "Custom Ops Grid",
                "description": "Host and List widgets",
                "widgets": [
                    {
                        "id": "w-host-1",
                        "widget_type": "HOST",
                        "title": "Router 1",
                        "grid_x": 1,
                        "grid_y": 1,
                        "grid_w": 4,
                        "grid_h": 1,
                        "catalog_item_id": "cat-rtr-2sya-01",
                    },
                    {
                        "id": "w-list-1",
                        "widget_type": "LIST",
                        "title": "Core Routers Global",
                        "grid_x": 5,
                        "grid_y": 1,
                        "grid_w": 8,
                        "grid_h": 1,
                        "list_id": "list-core-global-test",
                    },
                ],
            }
        ),
        content_type="application/json",
    )
    assert layout_resp.status_code == 200
    saved_dash = next(d for d in layout_resp.json()["dashboards"] if d["id"] == dash_id)
    assert len(saved_dash["widgets"]) == 2
    assert {w["widget_type"] for w in saved_dash["widgets"]} == {"HOST", "LIST"}


def test_teams_zones_and_rbac_management_endpoints() -> None:
    client = Client()
    # Create a new Team
    team_resp = client.post(
        "/api/v1/teams",
        data=json.dumps(
            {
                "action": "save",
                "code": "VOICE",
                "name": "Voice & UC Engineering",
                "description": "SIP trunks and media gateways",
                "members": ["joperator"],
            }
        ),
        content_type="application/json",
    )
    assert team_resp.status_code == 200
    assert any(t["code"] == "VOICE" for t in team_resp.json()["teams"])

    # Create a new Zone linked to CIDR
    zone_resp = client.post(
        "/api/v1/zones",
        data=json.dumps(
            {
                "action": "save_zone",
                "name": "Lab Transit Zone",
                "description": "Lab transit networks",
                "cidrs": ["198.18.0.0/15"],
                "priority": 150,
            }
        ),
        content_type="application/json",
    )
    assert zone_resp.status_code == 200
    assert any(z["name"] == "Lab Transit Zone" for z in zone_resp.json()["zones"])

    # IP lookup tester resolves 198.18.1.25 to Lab Transit Zone
    lookup_resp = client.post(
        "/api/v1/zones",
        data=json.dumps({"action": "test_ip", "ip": "198.18.1.25"}),
        content_type="application/json",
    )
    assert lookup_resp.status_code == 200
    assert lookup_resp.json()["resolution"]["winning_zone"]["name"] == "Lab Transit Zone"


def test_admin_view_as_capability_and_rbac_enforcement() -> None:
    client = Client()
    # 1. Default session is joperator (Global Admin) -> can_view_as is True
    view_as_resp = client.post(
        "/api/v1/simulator",
        data=json.dumps({"view_as_user_id": "usr-team-lead"}),
        content_type="application/json",
    )
    assert view_as_resp.status_code == 200
    snap = view_as_resp.json()
    assert snap["view_as"]["active"] is True
    assert snap["view_as"]["can_view_as"] is True
    assert snap["auth_user"]["username"] == "joperator"
    assert snap["user"]["username"] == "sam.reeves"
    # Sam Reeves is only in team-secops, so team-compute dashboard is not in Sam's visible dashboards
    dash_ids = {d["id"] for d in snap["dashboards"]}
    assert DASH_TEAM_COMPUTE_ID not in dash_ids
    assert DASH_TEAM_SECOPS_ID in dash_ids

    # 2. Exit View As restores joperator's own perspective
    exit_resp = client.post(
        "/api/v1/simulator",
        data=json.dumps({"view_as_user_id": ""}),
        content_type="application/json",
    )
    assert exit_resp.status_code == 200
    exit_snap = exit_resp.json()
    assert exit_snap["view_as"]["active"] is False
    assert exit_snap["user"]["username"] == "joperator"

    # 3. Non-admin user cannot use View As
    client.post(
        "/api/v1/simulator",
        data=json.dumps({"active_user_id": "usr-standard"}),
        content_type="application/json",
    )
    denied = client.post(
        "/api/v1/simulator",
        data=json.dumps({"view_as_user_id": "usr-admin"}),
        content_type="application/json",
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "PERMISSION_DENIED"


def test_add_existing_and_remove_dashboard_from_user_menu() -> None:
    client = Client()
    # Initially DASH_GLOBAL_NOC_ID is available but not pinned in joperator's menu
    initial = client.get("/api/v1/state").json()
    menu_ids = {d["id"] for d in initial["dashboards"]}
    avail_ids = {d["id"] for d in initial["available_dashboards"]}
    assert DASH_GLOBAL_NOC_ID in avail_ids
    assert DASH_GLOBAL_NOC_ID not in menu_ids

    # Add existing Global dashboard to user's menu (works with both UUID and legacy alias)
    add_resp = client.post(
        "/api/v1/dashboards",
        data=json.dumps({"action": "add_existing", "dashboard_id": DASH_GLOBAL_NOC_ID}),
        content_type="application/json",
    )
    assert add_resp.status_code == 200
    assert add_resp.json()["added_dashboard_id"] == DASH_GLOBAL_NOC_ID
    updated_menu_ids = {d["id"] for d in add_resp.json()["state"]["dashboards"]}
    assert DASH_GLOBAL_NOC_ID in updated_menu_ids

    # Remove it from user's menu without deleting the dashboard itself
    rem_resp = client.post(
        "/api/v1/dashboards",
        data=json.dumps({"action": "remove_from_menu", "dashboard_id": DASH_GLOBAL_NOC_ID}),
        content_type="application/json",
    )
    assert rem_resp.status_code == 200
    after_rem_ids = {d["id"] for d in rem_resp.json()["state"]["dashboards"]}
    assert DASH_GLOBAL_NOC_ID not in after_rem_ids
    assert DASH_GLOBAL_NOC_ID in {d["id"] for d in rem_resp.json()["state"]["available_dashboards"]}


def test_dashboard_always_display_and_update_properties() -> None:
    client = Client()
    # DASH_GLOBAL_NETOPS_ID has always_display=True by default and cannot be removed from menu
    rem_blocked = client.post(
        "/api/v1/dashboards",
        data=json.dumps({"action": "remove_from_menu", "dashboard_id": DASH_GLOBAL_NETOPS_ID}),
        content_type="application/json",
    )
    assert rem_blocked.status_code == 400
    assert "Always Display" in rem_blocked.json()["detail"]

    # Update properties of DASH_GLOBAL_NOC_ID to enable always_display and rename
    prop_resp = client.post(
        "/api/v1/dashboards",
        data=json.dumps(
            {
                "action": "update_properties",
                "dashboard_id": DASH_GLOBAL_NOC_ID,
                "title": "NOC Status Wallboard (Forced)",
                "description": "Updated description",
                "scope": "GLOBAL",
                "always_display": True,
            }
        ),
        content_type="application/json",
    )
    assert prop_resp.status_code == 200
    snap = prop_resp.json()["state"]
    noc_dash = next(d for d in snap["dashboards"] if d["id"] == DASH_GLOBAL_NOC_ID)
    assert noc_dash["title"] == "NOC Status Wallboard (Forced)"
    assert noc_dash["always_display"] is True
    assert noc_dash["in_user_menu"] is True


def test_list_item_reorder_and_sites_crud_and_protocol_specific_items() -> None:
    client = Client()
    # 1. Reorder items in list-global-routers
    reorder_resp = client.post(
        "/api/v1/lists",
        data=json.dumps(
            {
                "action": "reorder",
                "id": "list-global-routers",
                "item_ids": ["cat-rtr-3mel-02", "cat-rtr-2sya-01"],
            }
        ),
        content_type="application/json",
    )
    assert reorder_resp.status_code == 200
    rtr_list = next(lst for lst in reorder_resp.json()["lists"] if lst["id"] == "list-global-routers")
    assert rtr_list["item_ids"] == ["cat-rtr-3mel-02", "cat-rtr-2sya-01"]
    assert [it["id"] for it in rtr_list["items"]] == ["cat-rtr-3mel-02", "cat-rtr-2sya-01"]

    # 2. Pre-defined Sites CRUD (/api/v1/sites)
    site_create = client.post(
        "/api/v1/sites",
        data=json.dumps(
            {
                "action": "save",
                "code": "6PER",
                "name": "Perth West POP",
                "description": "Western Australia peering POP",
            }
        ),
        content_type="application/json",
    )
    assert site_create.status_code == 200
    created_site = next(s for s in site_create.json()["sites"] if s["code"] == "6PER")
    assert created_site["name"] == "Perth West POP"

    # 3. Protocol-specific Catalog Items: LOCAL_APP (command + args, no port), WEB (URL), RDP (default port 3389)
    local_app_resp = client.post(
        "/api/v1/catalog",
        data=json.dumps(
            {
                "action": "create",
                "title": "Wireshark Remote Capture",
                "protocol": "LOCAL_APP",
                "host": "/usr/bin/wireshark",
                "path_or_args": "-k -i eth0",
                "site": "6PER",
                "scope": "GLOBAL",
            }
        ),
        content_type="application/json",
    )
    assert local_app_resp.status_code == 200
    app_id = local_app_resp.json()["created_item_id"]
    app_item = next(c for c in local_app_resp.json()["state"]["catalog"] if c["id"] == app_id)
    assert app_item["protocol"] == "LOCAL_APP"
    assert app_item["port"] is None
    assert app_item["host_port_display"] == "/usr/bin/wireshark -k -i eth0"

    rdp_resp = client.post(
        "/api/v1/catalog",
        data=json.dumps(
            {
                "action": "create",
                "title": "Perth Jump Box",
                "protocol": "RDP",
                "host": "jump01.6per.ops.example.com",
                "site": "6PER",
                "scope": "GLOBAL",
            }
        ),
        content_type="application/json",
    )
    assert rdp_resp.status_code == 200
    rdp_id = rdp_resp.json()["created_item_id"]
    rdp_item = next(c for c in rdp_resp.json()["state"]["catalog"] if c["id"] == rdp_id)
    assert rdp_item["port"] == 3389
    assert rdp_item["host_port_display"] == "jump01.6per.ops.example.com:3389"


def test_explicit_dashboard_url_routing_and_default_dashboards() -> None:
    client = Client()
    # 1. Initially, joperator has no personal override -> inherits Default Global Dashboard
    snap0 = client.get("/api/v1/state").json()
    assert snap0["system_settings"]["default_global_dashboard_id"] == DASH_GLOBAL_NETOPS_ID
    assert snap0["user"]["default_dashboard_id"] is None
    assert snap0["user"]["effective_default_dashboard_id"] == DASH_GLOBAL_NETOPS_ID
    assert snap0["user"]["effective_default_dashboard_source"] == "SYSTEM_GLOBAL"
    assert snap0["user"]["effective_default_dashboard_url"] == f"/dashboard/{DASH_GLOBAL_NETOPS_ID}"

    # Visiting /dashboard resolves data-initial-dashboard-id to DASH_GLOBAL_NETOPS_ID
    dash_root = client.get("/dashboard")
    assert dash_root.status_code == 200
    assert f'data-initial-dashboard-id="{DASH_GLOBAL_NETOPS_ID}"'.encode() in dash_root.content

    # Visiting /dashboard/<dash-uuid> resolves directly to that dashboard
    dash_specific = client.get(f"/dashboard/{DASH_TEAM_COMPUTE_ID}")
    assert dash_specific.status_code == 200
    assert f'data-initial-dashboard-id="{DASH_TEAM_COMPUTE_ID}"'.encode() in dash_specific.content
    assert b'data-initial-edit="false"' in dash_specific.content

    # Visiting /dashboard/<dash-uuid>/edit resolves directly in edit mode
    dash_edit = client.get(f"/dashboard/{DASH_TEAM_COMPUTE_ID}/edit")
    assert dash_edit.status_code == 200
    assert f'data-initial-dashboard-id="{DASH_TEAM_COMPUTE_ID}"'.encode() in dash_edit.content
    assert b'data-initial-edit="true"' in dash_edit.content

    # 2. User sets their own personal Default Dashboard from the list available to them
    set_user_def = client.post(
        "/api/v1/dashboards",
        data=json.dumps({"action": "set_user_default", "dashboard_id": DASH_PERSONAL_BENCH_ID}),
        content_type="application/json",
    )
    assert set_user_def.status_code == 200
    snap1 = set_user_def.json()["state"]
    assert snap1["user"]["default_dashboard_id"] == DASH_PERSONAL_BENCH_ID
    assert snap1["user"]["effective_default_dashboard_id"] == DASH_PERSONAL_BENCH_ID
    assert snap1["user"]["effective_default_dashboard_source"] == "USER"

    # Visiting /dashboard now resolves to DASH_PERSONAL_BENCH_ID
    dash_user_root = client.get("/dashboard")
    assert f'data-initial-dashboard-id="{DASH_PERSONAL_BENCH_ID}"'.encode() in dash_user_root.content

    # 3. Clearing personal Default Dashboard via /api/v1/profile reverts to App-Wide Default Global Dashboard
    clear_resp = client.post(
        "/api/v1/profile",
        data=json.dumps({"default_dashboard_id": ""}),
        content_type="application/json",
    )
    assert clear_resp.status_code == 200
    snap2 = clear_resp.json()
    assert snap2["user"]["default_dashboard_id"] is None
    assert snap2["user"]["effective_default_dashboard_id"] == DASH_GLOBAL_NETOPS_ID
    assert snap2["user"]["effective_default_dashboard_source"] == "SYSTEM_GLOBAL"


def test_system_default_global_dashboard_rbac_and_protection() -> None:
    client = Client()
    # 1. Global Admin updates App-Wide Default Global Dashboard via /api/v1/settings
    upd_global = client.post(
        "/api/v1/settings",
        data=json.dumps({"default_global_dashboard_id": DASH_GLOBAL_NOC_ID}),
        content_type="application/json",
    )
    assert upd_global.status_code == 200
    snap = upd_global.json()
    assert snap["system_settings"]["default_global_dashboard_id"] == DASH_GLOBAL_NOC_ID
    assert snap["user"]["effective_default_dashboard_id"] == DASH_GLOBAL_NOC_ID
    # Also ensures the new Default Global Dashboard is pinned in menu
    assert DASH_GLOBAL_NOC_ID in {d["id"] for d in snap["dashboards"]}

    # 2. Non-GLOBAL dashboard cannot be set as App-Wide Default Global Dashboard
    bad_scope = client.post(
        "/api/v1/settings",
        data=json.dumps({"default_global_dashboard_id": DASH_TEAM_COMPUTE_ID}),
        content_type="application/json",
    )
    assert bad_scope.status_code == 400
    assert bad_scope.json()["error_code"] == "VALIDATION_ERROR"
    assert "GLOBAL scope" in bad_scope.json()["detail"]

    # 3. Active Default Global Dashboard cannot be deleted
    del_blocked = client.post(
        "/api/v1/dashboards",
        data=json.dumps({"action": "delete", "id": DASH_GLOBAL_NOC_ID}),
        content_type="application/json",
    )
    assert del_blocked.status_code == 400
    assert del_blocked.json()["error_code"] == "VALIDATION_ERROR"
    assert "Default Global Dashboard" in del_blocked.json()["detail"]

    # 4. Non-admin user cannot change the App-Wide Default Global Dashboard
    client.post(
        "/api/v1/simulator",
        data=json.dumps({"active_user_id": "usr-standard"}),
        content_type="application/json",
    )
    denied = client.post(
        "/api/v1/settings",
        data=json.dumps({"default_global_dashboard_id": DASH_GLOBAL_NETOPS_ID}),
        content_type="application/json",
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "PERMISSION_DENIED"



def test_health_reports_database_and_version_stage() -> None:
    client = Client()
    body = client.get("/api/v1/health").json()
    assert body["database"]["ok"] is True
    assert body["stage"] == "stage-2-relational"
    assert client.get("/api/v1/version").json()["stage"] == 2


def test_export_api_requires_global_admin() -> None:
    client = Client()
    resp = client.get("/api/v1/export")
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["format"] == "panic-export"
    assert doc["sites"] and doc["dashboards"]
    assert all("password_hash" not in u for u in doc["users"])
    shared = client.get("/api/v1/export?shared_only=true").json()
    assert shared["users"] == []
    assert all(d["scope"] != "PERSONAL" for d in shared["dashboards"])

    non_admin = next(u for u in STORE.users if "GLOBAL_ADMIN" not in u.permissions)
    client.post(
        "/api/v1/simulator", data=json.dumps({"active_user_id": non_admin.id}), content_type="application/json"
    )
    assert client.get("/api/v1/export").status_code == 403


def test_export_then_import_on_clean_database_reproduces_state(tmp_path: object) -> None:
    from pathlib import Path

    from django.core.management import call_command

    from panic_server.portability import export_state

    STORE.refresh()
    before = export_state(STORE)
    out = Path(str(tmp_path)) / "export.json"
    call_command("panic_export", "--output", str(out))
    STORE.wipe()
    STORE.refresh()
    assert STORE.sites == []
    call_command("panic_import", str(out))
    STORE.refresh()
    after = export_state(STORE)
    for section in ("sites", "teams", "zones", "users", "catalog", "lists", "dashboards", "system_settings"):
        if section == "system_settings":
            assert before[section] == after[section]
        else:
            assert sorted(before[section], key=lambda o: o["id"]) == sorted(
                after[section], key=lambda o: o["id"]
            ), section


def test_import_rejects_foreign_documents() -> None:
    from panic_server.portability import ImportValidationError, import_state

    with pytest.raises(ImportValidationError):
        import_state(STORE, {"format": "something-else"})

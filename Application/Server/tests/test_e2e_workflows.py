"""End-to-end workflows in production-like mode: session auth + CSRF + relational persistence +
trusted-proxy zone resolution + RBAC + launchers (T-S4-02).

Plus a documentation guard: every ``PANIC_*`` setting must be documented in CONFIGURATION.md.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.http import HttpResponse
from django.test import Client, override_settings

from panic_server.auth import oidc
from panic_server.portability import export_state
from panic_server.state import DASH_GLOBAL_NOC_ID, DASH_PERSONAL_BENCH_ID, STORE
from panic_server.store_db import DatabasePortalStore

ROOT = Path(__file__).resolve().parents[3]
ADMIN_PASSWORD = "e2e-bootstrap-passphrase"
PROXY = "192.0.2.10"

PROD_LIKE: dict[str, Any] = {
    "PANIC_AUTH_MODE": "session",
    "PANIC_DEV_SIMULATOR_ENABLED": False,
    "PANIC_BOOTSTRAP_ADMIN_USER": "e2e-admin",
    "PANIC_BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASSWORD,
    "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
    "PANIC_TRUST_PROXY_HEADERS": True,
    "PANIC_TRUSTED_PROXY_CIDRS": [f"{PROXY}/32"],
    "PANIC_OIDC_ENABLED": True,
    "PANIC_OIDC_ISSUER": "https://idp.example.com",
    "PANIC_OIDC_CLIENT_ID": "panic",
    "PANIC_OIDC_AUTHORIZE_URL": "https://idp.example.com/authorize",
    "PANIC_OIDC_TOKEN_URL": "https://idp.example.com/token",
    "PANIC_OIDC_USERINFO_URL": "",
    "PANIC_OIDC_REDIRECT_URI": "https://panic.example.com/auth/oidc/callback",
    "PANIC_RBAC_ADMIN_GROUPS": ["panic-admins"],
    "PANIC_RBAC_GLOBAL_CONTRIB_GROUPS": [],
    "PANIC_RBAC_TEAM_CONTRIB_GROUPS": [],
}


@pytest.fixture(autouse=True)
def _prod_like() -> Iterator[None]:
    with override_settings(**PROD_LIKE):
        yield


class Browser:
    """A CSRF-enforcing client that behaves like ``panic.js`` (token header on writes)."""

    def __init__(self, client_ip: str = "198.51.100.20") -> None:
        self.client = Client(enforce_csrf_checks=True, REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=client_ip)

    def token(self) -> str:
        if "panic_csrftoken" not in self.client.cookies:
            # Login page when signed out, the portal shell (csrf meta tag) when signed in.
            self.client.get("/login", follow=True)
        return self.client.cookies["panic_csrftoken"].value

    def login(self, username: str = "e2e-admin", password: str = ADMIN_PASSWORD) -> HttpResponse:
        return self.client.post(
            "/login", {"username": username, "password": password, "csrfmiddlewaretoken": self.token()}
        )

    def api(self, method: str, path: str, body: dict[str, Any] | None = None) -> HttpResponse:
        fn = getattr(self.client, method.lower())
        return fn(path, json.dumps(body or {}), content_type="application/json", headers={"X-CSRFToken": self.token()})

    def state(self) -> dict[str, Any]:
        return self.client.get("/api/v1/state").json()


def _oidc_login(browser: Browser, username: str, groups: list[str]) -> None:
    import base64
    import time
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(browser.client.get("/auth/oidc/login")["Location"]).query)
    claims = {
        "iss": "https://idp.example.com",
        "aud": "panic",
        "exp": time.time() + 60,
        "nonce": q["nonce"][0],
        "preferred_username": username,
        "groups": groups,
    }
    token = "x." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".y"
    with mock.patch.object(oidc, "_http_post_form", return_value={"id_token": token}):
        assert browser.client.get(f"/auth/oidc/callback?state={q['state'][0]}&code=c").status_code == 302


def _fresh() -> DatabasePortalStore:
    store = DatabasePortalStore()
    store.refresh()
    return store


def test_admin_session_csrf_catalog_persistence_audit_and_export() -> None:
    b = Browser()
    assert b.client.get("/catalog").status_code == 302
    assert b.login().status_code == 302

    # A write without the CSRF header is rejected even when signed in.
    no_token = b.client.post("/api/v1/catalog", "{}", content_type="application/json")
    assert no_token.status_code == 403 and no_token.json()["error_code"] == "CSRF_FAILED"

    created = b.api(
        "post",
        "/api/v1/catalog",
        {
            "action": "create",
            "title": "E2E Edge Router",
            "protocol": "SSH",
            "host": "edge-e2e.network.example.com",
            "port": 22,
            "site": "2SYA",
            "scope": "GLOBAL",
            "zone_ids": ["zone-corp"],
        },
    )
    assert created.status_code == 200, created.content
    assert any(c.title == "E2E Edge Router" for c in _fresh().catalog)
    actions = [(a.action, a.actor_username) for a in STORE.query_audit(actor="e2e-admin", limit=20)]
    assert ("auth.login", "e2e-admin") in actions
    assert any(a.startswith("catalog.") for a, _ in actions)
    assert any(c["title"] == "E2E Edge Router" for c in export_state(_fresh())["catalog"])

    assert b.api("post", "/logout").status_code == 302
    assert b.client.get("/api/v1/state").status_code == 401


def test_proxy_resolved_zone_drives_reachability_and_spoofing_is_ignored() -> None:
    dmz = Browser(client_ip="192.0.2.77")
    dmz.login()
    resp = dmz.client.get("/api/v1/state")
    assert resp["X-Client-IP"] == "192.0.2.77"
    assert resp["X-Security-Zone"] == "zone-dmz"
    snap = resp.json()
    assert snap["simulation"]["simulated_ip"] == "192.0.2.77"
    rtr = next(c for c in snap["catalog"] if c["id"] == "cat-rtr-2sya-01")
    assert rtr["reachability"]["reachable"] is True

    corp = Browser(client_ip="198.51.100.20")
    corp.login()
    corp_snap = corp.client.get("/api/v1/state")
    assert corp_snap["X-Security-Zone"] == "zone-corp"
    rtr = next(c for c in corp_snap.json()["catalog"] if c["id"] == "cat-rtr-2sya-01")
    assert rtr["reachability"]["reachable"] is False

    # Untrusted peer forging X-Forwarded-For: the header is ignored.
    spoof = Client(REMOTE_ADDR="203.0.113.9", HTTP_X_FORWARDED_FOR="192.0.2.77")
    assert spoof.get("/api/v1/health")["X-Client-IP"] == "203.0.113.9"
    # Live mode refuses manual IP / zone simulation.
    corp.api("post", "/api/v1/simulator", {"simulated_ip": "192.0.2.77", "override_zone_id": "zone-dmz"})
    assert corp.client.get("/api/v1/state")["X-Security-Zone"] == "zone-corp"


def test_multi_user_rbac_view_as_and_default_dashboard_precedence() -> None:
    admin = Browser()
    admin.login()
    operator = Browser()
    _oidc_login(operator, "casey.e2e", ["staff"])
    casey = STORE.get_user_by_username("casey.e2e")
    assert casey is not None and casey.permissions == []

    # Non-admin: GLOBAL create denied, PERSONAL allowed, export and View As denied.
    base = {"action": "create", "protocol": "SSH", "port": 22, "site": "2SYA"}
    denied = operator.api(
        "post", "/api/v1/catalog", {**base, "title": "No", "host": "no.example.com", "scope": "GLOBAL"}
    )
    assert denied.status_code == 403
    ok = operator.api(
        "post", "/api/v1/catalog", {**base, "title": "Mine", "host": "mine.example.com", "scope": "PERSONAL"}
    )
    assert ok.status_code == 200
    assert operator.client.get("/api/v1/export").status_code == 403
    assert operator.api("post", "/api/v1/simulator", {"view_as_user_id": "usr-admin"}).status_code == 403

    # Default dashboard: app-wide default until the user picks their own.
    assert operator.state()["user"]["effective_default_dashboard_source"] != "USER"
    admin_state = admin.state()
    assert admin_state["user"]["effective_default_dashboard_id"] == STORE.system_settings.default_global_dashboard_id

    # Admin "View As" casey sees casey's personal item and perspective, then exits.
    assert admin.api("post", "/api/v1/simulator", {"view_as_user_id": casey.id}).status_code == 200
    as_casey = admin.state()
    assert as_casey["user"]["username"] == "casey.e2e"
    assert any(c["title"] == "Mine" for c in as_casey["catalog"])
    admin.api("post", "/api/v1/simulator", {"view_as_user_id": None})
    assert admin.state()["user"]["username"] == "e2e-admin"
    assert not any(c["title"] == "Mine" for c in admin.state()["catalog"])

    # Admin's own user-level default overrides the global default and persists.
    resp = admin.api("post", "/api/v1/dashboards", {"action": "set_user_default", "dashboard_id": DASH_GLOBAL_NOC_ID})
    assert resp.status_code == 200
    me = _fresh().get_user_by_username("e2e-admin")
    assert me is not None and me.default_dashboard_id == DASH_GLOBAL_NOC_ID
    assert DASH_PERSONAL_BENCH_ID not in {d["id"] for d in operator.state().get("accessible_dashboards", [])}


def test_list_order_and_widget_layout_persist_across_reload() -> None:
    b = Browser()
    b.login()
    order = ["cat-rtr-3mel-02", "cat-rtr-2sya-01"]
    assert (
        b.api(
            "post", "/api/v1/lists", {"action": "reorder", "id": "list-global-routers", "item_ids": order}
        ).status_code
        == 200
    )
    assert next(lst for lst in _fresh().lists if lst.id == "list-global-routers").item_ids[:2] == order

    dash_id = b.api("post", "/api/v1/dashboards", {"action": "create", "title": "E2E Grid", "scope": "GLOBAL"}).json()[
        "created_dashboard_id"
    ]
    widgets = [
        {
            "id": "w-a",
            "widget_type": "HOST",
            "title": "A",
            "grid_x": 1,
            "grid_y": 1,
            "grid_w": 6,
            "grid_h": 2,
            "catalog_item_id": "cat-rtr-2sya-01",
        },
        {
            "id": "w-b",
            "widget_type": "LIST",
            "title": "B",
            "grid_x": 7,
            "grid_y": 1,
            "grid_w": 6,
            "grid_h": 3,
            "list_id": "list-global-routers",
        },
    ]
    resp = b.api("put", f"/api/v1/dashboards/{dash_id}/layout", {"title": "E2E Grid", "widgets": widgets})
    assert resp.status_code == 200, resp.content
    stored = next(d for d in _fresh().dashboards if d.id == dash_id)
    assert [(w.id, w.grid_x, w.grid_w, w.grid_h) for w in stored.widgets] == [("w-a", 1, 6, 2), ("w-b", 7, 6, 3)]


def test_rdp_and_ssh_launchers() -> None:
    b = Browser(client_ip="192.0.2.77")
    b.login()
    rdp = b.client.get("/api/v1/launch/rdp/cat-rdp-bastion-01.rdp?user=ops.e2e")
    assert rdp.status_code == 200
    body = rdp.content.decode()
    assert "full address:s:" in body and "username:s:ops.e2e" in body
    assert "password" not in body.lower()
    assert rdp["Cache-Control"].startswith("no-store")
    ssh = next(c for c in b.state()["catalog"] if c["id"] == "cat-rtr-2sya-01")
    assert ssh["launch"]["ssh_command"].startswith("ssh ")
    assert ssh["launch"]["ssh_uri"].startswith("ssh://")


def test_configuration_doc_covers_every_setting() -> None:
    settings_src = (ROOT / "Application/Server/panic_server/settings.py").read_text()
    entry_src = (ROOT / "Build/Containers/server/entrypoint.sh").read_text()
    names = set(re.findall(r'env_\w+\("(PANIC_[A-Z0-9_]+)"', settings_src))
    names |= set(re.findall(r"\$\{(PANIC_[A-Z0-9_]+)", entry_src))
    doc = (ROOT / "Documents/Operations/CONFIGURATION.md").read_text()
    missing = sorted(n for n in names if f"`{n}`" not in doc)
    assert not missing, f"undocumented settings: {missing}"
    deploy = (ROOT / "Documents/Operations/DEPLOYMENT.md").read_text()
    assert "CONFIGURATION.md" in deploy and "panic_export" in deploy

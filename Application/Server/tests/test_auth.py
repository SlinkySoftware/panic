"""Session authentication, bootstrap admin, login/logout and "View As" in session mode (T-S3-01)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.http import HttpResponse
from django.test import Client, override_settings

from panic_server.state import STORE

SESSION_SETTINGS: dict[str, Any] = {
    "PANIC_AUTH_MODE": "session",
    "PANIC_DEV_SIMULATOR_ENABLED": False,
    "PANIC_AUTH_LOCAL_ENABLED": True,
    "PANIC_BOOTSTRAP_ADMIN_USER": "bootadmin",
    "PANIC_BOOTSTRAP_ADMIN_PASSWORD": "correct-horse-battery-staple",
    "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
}


@pytest.fixture(autouse=True)
def _session_mode() -> Iterator[None]:
    with override_settings(**SESSION_SETTINGS):
        yield


BOOT_PASSWORD = SESSION_SETTINGS["PANIC_BOOTSTRAP_ADMIN_PASSWORD"]


def _login(client: Client, username: str = "bootadmin", password: str | None = None) -> HttpResponse:
    return client.post("/login", {"username": username, "password": password or BOOT_PASSWORD, "next": "/catalog"})


def test_unauthenticated_requests_redirect_or_401() -> None:
    client = Client()
    resp = client.get("/catalog")
    assert resp.status_code == 302
    assert resp["Location"].startswith("/login?next=/catalog")
    api = client.get("/api/v1/state")
    assert api.status_code == 401
    assert api.json()["error_code"] == "UNAUTHENTICATED"
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/login").status_code == 200


def test_bootstrap_admin_login_view_as_and_logout() -> None:
    client = Client()
    resp = _login(client)
    assert resp.status_code == 302
    assert resp["Location"] == "/catalog"
    state = client.get("/api/v1/state").json()
    assert state["user"]["username"] == "bootadmin"
    assert "GLOBAL_ADMIN" in state["user"]["permissions"]

    target = next(u for u in STORE.users if u.username == "sam.reeves")
    r = client.post("/api/v1/simulator", json.dumps({"view_as_user_id": target.id}), content_type="application/json")
    assert r.status_code == 200
    assert client.get("/api/v1/state").json()["user"]["username"] == "sam.reeves"
    client.post("/api/v1/simulator", json.dumps({"view_as_user_id": None}), content_type="application/json")
    assert client.get("/api/v1/state").json()["user"]["username"] == "bootadmin"

    # User switching and simulator reset are disabled outside simulator mode.
    denied = client.post(
        "/api/v1/simulator", json.dumps({"active_user_id": target.id}), content_type="application/json"
    )
    assert denied.status_code == 403
    assert (
        client.post("/api/v1/state", json.dumps({"action": "reset"}), content_type="application/json").status_code
        == 403
    )

    assert b"Sign out" in client.get("/catalog").content
    out = client.post("/logout")
    assert out.status_code == 302
    assert client.get("/api/v1/state").status_code == 401
    actions = [a.action for a in STORE.query_audit(limit=50)]
    assert "auth.login" in actions and "auth.logout" in actions


def test_bad_password_and_unknown_user_rejected() -> None:
    client = Client()
    assert _login(client, password="wrong").status_code == 401
    assert _login(client, username="nobody").status_code == 401
    # Seeded fixture users have no local password and cannot sign in.
    assert _login(client, username="joperator", password="").status_code == 401
    assert client.get("/api/v1/state").status_code == 401
    assert "auth.login_failed" in [a.action for a in STORE.query_audit(limit=10)]


def test_open_redirect_is_blocked() -> None:
    client = Client()
    resp = client.post(
        "/login",
        {"username": "bootadmin", "password": "correct-horse-battery-staple", "next": "https://evil.example.net/"},
    )
    assert resp["Location"] == "/"


def test_logout_requires_post_and_csrf() -> None:
    client = Client(enforce_csrf_checks=True)
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 403
    login_page = client.get("/login")
    token = login_page.cookies["panic_csrftoken"].value
    resp = client.post(
        "/login",
        {"username": "bootadmin", "password": "correct-horse-battery-staple", "csrfmiddlewaretoken": token},
    )
    assert resp.status_code == 302


def test_simulator_mode_needs_no_login() -> None:
    with override_settings(PANIC_AUTH_MODE="simulator", PANIC_DEV_SIMULATOR_ENABLED=True):
        client = Client()
        assert client.get("/api/v1/state").status_code == 200
        assert client.get("/login").status_code == 302

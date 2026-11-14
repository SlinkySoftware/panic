"""CSRF enforcement, security headers, rate limiting and audit filtering (T-S3-04)."""

from __future__ import annotations

import json

from django.core.cache import cache
from django.test import Client, override_settings

from panic_server.state import STORE


def test_security_headers_on_html_api_and_errors() -> None:
    client = Client()
    for path in ("/", "/api/v1/health", "/api/v1/state", "/api/v1/launch/rdp/missing.rdp"):
        resp = client.get(path, follow=False)
        assert "default-src 'self'" in resp["Content-Security-Policy"], path
        assert "frame-ancestors 'none'" in resp["Content-Security-Policy"]
        assert resp["X-Content-Type-Options"] == "nosniff"
        assert resp["Referrer-Policy"] == "same-origin"
        assert "camera=()" in resp["Permissions-Policy"]


def test_csrf_enforced_on_state_changing_api() -> None:
    client = Client(enforce_csrf_checks=True)
    page = client.get("/catalog")
    assert b'name="csrf-token"' in page.content
    token = page.cookies["panic_csrftoken"].value
    body = json.dumps({"unreachable_policy": "HIDE"})

    denied = client.post("/api/v1/simulator", body, content_type="application/json")
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "CSRF_FAILED"
    bad = client.post("/api/v1/simulator", body, content_type="application/json", headers={"X-CSRFToken": "x" * 32})
    assert bad.status_code == 403

    ok = client.post("/api/v1/simulator", body, content_type="application/json", headers={"X-CSRFToken": token})
    assert ok.status_code == 200
    # Safe methods never need a token.
    assert client.get("/api/v1/state").status_code == 200


def test_rate_limit_login_and_api() -> None:
    cache.clear()
    with override_settings(
        PANIC_RATE_LIMIT_ENABLED=True,
        PANIC_RATE_LIMIT_LOGIN="2/60",
        PANIC_RATE_LIMIT_API="3/60",
        PANIC_AUTH_MODE="session",
        PANIC_DEV_SIMULATOR_ENABLED=False,
    ):
        client = Client()
        codes = [client.post("/login", {"username": "x", "password": "y"}).status_code for _ in range(3)]
        assert codes == [401, 401, 429]
        limited = client.post("/login", {"username": "x", "password": "y"})
        assert limited.json()["error_code"] == "RATE_LIMITED"
        assert int(limited["Retry-After"]) >= 1
        api_codes = [
            client.post("/api/v1/simulator", "{}", content_type="application/json").status_code for _ in range(4)
        ]
        assert api_codes[-1] == 429
        # Reads are not limited.
        assert client.get("/api/v1/health").status_code == 200
    cache.clear()


def test_audit_api_filters() -> None:
    client = Client()
    STORE.record_audit(action="catalog.create", target_type="catalog_item", target_id="cat-x1", summary="needle one")
    STORE.record_audit(action="catalog.delete", target_type="catalog_item", target_id="cat-x2", summary="other")
    STORE.record_audit(action="auth.login", target_type="user_account", target_id="usr-z", summary="needle two")

    def fetch(qs: str) -> list[dict[str, str]]:
        resp = client.get(f"/api/v1/audit?{qs}")
        assert resp.status_code == 200
        return resp.json()["entries"]

    assert {e["target_id"] for e in fetch("action=catalog.")} >= {"cat-x1", "cat-x2"}
    assert all(e["action"].startswith("catalog.") for e in fetch("action=catalog."))
    assert {e["target_id"] for e in fetch("q=needle")} == {"cat-x1", "usr-z"}
    assert {e["target_id"] for e in fetch("q=needle&target_type=user_account")} == {"usr-z"}
    assert len(fetch("limit=1")) == 1
    assert client.get("/api/v1/audit?limit=abc").status_code == 400
    assert client.get("/audit?actor=joperator").status_code == 200

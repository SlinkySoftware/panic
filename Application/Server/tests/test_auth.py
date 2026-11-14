"""Login/logout, rate limiting, disabled-user rejection, and request-context isolation (T-S6-04,
T-S6-06).

Replaces the Stage 1-5 STORE-backed ``test_auth.py``/``test_security.py``: same behaviours
(sign-in, sign-out, per-IP/per-username rate limiting, disabled accounts), now against the
Mongo-backed store and the lock-free, per-request ``RequestContext``. T-S6-06 moves the actual
login/logout surface from the old ``/login``/``/logout`` (now deleted) to the real JSON contract,
``/api/v1/auth/login``/``/api/v1/auth/logout`` -- these tests move with it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from django.test import Client, RequestFactory, override_settings
from pymongo.database import Database

from panic_server.context import SESSION_USER_KEY, build_request_context
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]

ADMIN_USER = "test-bootstrap-admin"
ADMIN_PASSWORD = "a-reasonably-long-bootstrap-passphrase"


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)


@pytest.fixture
def _bootstrap_admin() -> Iterator[None]:
    with override_settings(
        PANIC_BOOTSTRAP_ADMIN_USER=ADMIN_USER,
        PANIC_BOOTSTRAP_ADMIN_PASSWORD=ADMIN_PASSWORD,
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    ):
        yield


def _login(client: Client, username: str, password: str, **extra: str) -> object:
    return client.post(
        "/api/v1/auth/login",
        {"username": username, "password": password},
        content_type="application/json",
        **extra,
    )


@pytest.mark.usefixtures("_bootstrap_admin")
def test_login_success_sets_session_and_audits(mongo_db: Database) -> None:
    client = Client()
    resp = _login(client, ADMIN_USER, ADMIN_PASSWORD)
    assert resp.status_code == 200
    assert resp.json()["me"]["username"] == ADMIN_USER
    assert client.session[SESSION_USER_KEY]

    user = users_repo.get_user_by_username(mongo_db, ADMIN_USER)
    assert user is not None
    actions = [a.action for a in audit_repo.list_audit(mongo_db, actor_username=ADMIN_USER, limit=10)]
    assert "auth.login" in actions

    assert client.get("/api/v1/health").status_code in {200, 503}  # public path, no auth required


@pytest.mark.usefixtures("_bootstrap_admin")
def test_login_failure_wrong_password_returns_401_and_audits(mongo_db: Database) -> None:
    client = Client()
    resp = _login(client, ADMIN_USER, "wrong")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"
    actions = [a.action for a in audit_repo.list_audit(mongo_db, action="auth.login_failed", limit=10)]
    assert "auth.login_failed" in actions


def test_auth_providers_is_public() -> None:
    client = Client()
    resp = client.get("/api/v1/auth/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["local_enabled"] is True
    assert "oidc" in body and "enabled" in body["oidc"]


def test_auth_csrf_sets_cookie() -> None:
    client = Client()
    resp = client.get("/api/v1/auth/csrf")
    assert resp.status_code == 204
    assert "panic_csrftoken" in resp.cookies


@pytest.mark.usefixtures("_bootstrap_admin")
def test_logout_clears_session(mongo_db: Database) -> None:
    client = Client()
    _login(client, ADMIN_USER, ADMIN_PASSWORD)
    assert client.session.get(SESSION_USER_KEY)
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    assert not client.session.get(SESSION_USER_KEY)


def test_logout_requires_a_session() -> None:
    client = Client()
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHENTICATED"


@pytest.mark.usefixtures("_bootstrap_admin")
def test_disabled_user_cannot_sign_in(mongo_db: Database) -> None:
    client = Client()
    _login(client, ADMIN_USER, ADMIN_PASSWORD)
    assert client.session.get(SESSION_USER_KEY)

    user = users_repo.get_user_by_username(mongo_db, ADMIN_USER)
    assert user is not None
    users_repo.update_user(mongo_db, user.id, user.version, disabled=True)

    # A fresh login attempt is refused.
    fresh = Client()
    resp = _login(fresh, ADMIN_USER, ADMIN_PASSWORD)
    assert resp.status_code == 401

    # The already-authenticated session is rejected on the next request (AR-2.11) and flushed.
    resp2 = client.get("/api/v1/does-not-exist-but-is-under-api")
    assert resp2.status_code == 401
    assert not client.session.get(SESSION_USER_KEY)


@pytest.mark.usefixtures("_bootstrap_admin")
def test_rate_limit_login_by_ip(mongo_db: Database) -> None:
    with override_settings(PANIC_RATE_LIMIT_LOGIN="2/60"):
        client = Client()
        for _ in range(2):
            resp = _login(client, "nope", "nope", REMOTE_ADDR="203.0.113.55")
            assert resp.status_code == 401
        blocked = _login(client, "nope", "nope", REMOTE_ADDR="203.0.113.55")
        assert blocked.status_code == 429
        assert blocked.json()["error_code"] == "RATE_LIMITED"
        assert "Retry-After" in blocked


@pytest.mark.usefixtures("_bootstrap_admin")
def test_rate_limit_login_by_username_spans_different_ips(mongo_db: Database) -> None:
    with override_settings(PANIC_RATE_LIMIT_LOGIN="2/60"):
        client = Client()
        for ip in ("203.0.113.61", "203.0.113.62"):
            resp = _login(client, "shared-victim", "nope", REMOTE_ADDR=ip)
            assert resp.status_code == 401
        blocked = _login(client, "shared-victim", "nope", REMOTE_ADDR="203.0.113.63")
        assert blocked.status_code == 429


def _make_request(user_id: str, path: str = "/api/v1/whatever"):  # type: ignore[no-untyped-def]
    """A minimal fake request: just enough for ``build_request_context`` (no Django machinery)."""
    req = RequestFactory().get(path, REMOTE_ADDR="127.0.0.1")
    req.session = {SESSION_USER_KEY: user_id}  # type: ignore[assignment] # a plain dict satisfies ``.get``
    return req


def test_concurrent_requests_from_different_users_never_cross_identities(mongo_db: Database) -> None:
    """Acceptance: two concurrent requests from different users in one worker never see each
    other's identity. ``RequestContext`` is built purely from each request's own session, with
    no process-level cache or lock, so this must hold under real thread interleaving."""
    alice = users_repo.create_user(mongo_db, username="alice.ctx", display_name="Alice", default_remote_user="alice")
    bob = users_repo.create_user(mongo_db, username="bob.ctx", display_name="Bob", default_remote_user="bob")

    errors: list[str] = []
    iterations = 200

    def worker(user_id: str, expected_username: str) -> None:
        for _ in range(iterations):
            ctx = build_request_context(_make_request(user_id))
            if ctx.real_user is None or ctx.real_user.username != expected_username:
                errors.append(f"expected {expected_username}, got {getattr(ctx.real_user, 'username', None)}")

    t1 = threading.Thread(target=worker, args=(alice.id, "alice.ctx"))
    t2 = threading.Thread(target=worker, args=(bob.id, "bob.ctx"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []

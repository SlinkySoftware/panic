"""OIDC and LDAP adapters, and external-identity provisioning (T-S3-02, T-S6-04).

``panic_common.claim_mapping`` is gone (ADR-0001 decision 11): external identity is for
authentication only, so there is no group -> RBAC/team mapping left to test. What remains is
provisioning itself (first sign-in gets no permissions/teams; a later sign-in only refreshes
``display_name``/``last_login_at``) plus the adapters' own protocol-level behaviour (OIDC state/
nonce/PKCE, LDAP filter escaping -- unchanged, still pure/mocked, no STORE dependency).
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client, override_settings
from pymongo.database import Database

from panic_common.models import PermissionFlag
from panic_server.auth import ldap_auth, oidc
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]

OIDC = {
    "PANIC_OIDC_ENABLED": True,
    "PANIC_OIDC_ISSUER": "https://idp.example.com",
    "PANIC_OIDC_CLIENT_ID": "panic",
    "PANIC_OIDC_CLIENT_SECRET": "s3cret",
    "PANIC_OIDC_AUTHORIZE_URL": "https://idp.example.com/authorize",
    "PANIC_OIDC_TOKEN_URL": "https://idp.example.com/token",
    "PANIC_OIDC_USERINFO_URL": "https://idp.example.com/userinfo",
    "PANIC_OIDC_REDIRECT_URI": "https://panic.example.com/auth/oidc/callback",
}


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)


def _jwt(claims: dict[str, Any]) -> str:
    def enc(o: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()

    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


@pytest.fixture
def oidc_settings() -> Iterator[None]:
    with override_settings(**OIDC):
        yield


def _start(client: Client) -> dict[str, str]:
    resp = client.get("/auth/oidc/login?next=/lists")
    assert resp.status_code == 302
    q = parse_qs(urlparse(resp["Location"]).query)
    assert q["code_challenge_method"] == ["S256"]
    return {k: v[0] for k, v in q.items()}


def test_oidc_first_sign_in_provisions_user_with_no_permissions_or_teams(
    mongo_db: Database, oidc_settings: None
) -> None:
    client = Client()
    q = _start(client)
    id_token = _jwt(
        {
            "iss": "https://idp.example.com",
            "aud": "panic",
            "exp": time.time() + 300,
            "nonce": q["nonce"],
            "sub": "abc",
            "preferred_username": "casey.sso",
            "name": "Casey SSO",
        }
    )
    with (
        mock.patch.object(oidc, "_http_post_form", return_value={"id_token": id_token, "access_token": "at"}),
        mock.patch.object(
            oidc,
            "_http_get_json",
            return_value={"sub": "abc", "groups": ["panic-global", "network-engineers"]},
        ),
    ):
        resp = client.get(f"/auth/oidc/callback?state={q['state']}&code=xyz")
    assert resp.status_code == 302 and resp["Location"] == "/lists"

    user = users_repo.get_user_by_username(mongo_db, "casey.sso")
    assert user is not None
    assert user.display_name == "Casey SSO"
    # The directory sent groups ("panic-global", "network-engineers"), but T-S6-04 deletes every
    # group -> RBAC/team mapping: a first external sign-in always gets no permissions, no teams.
    assert user.permissions == []
    assert user.team_ids == []
    assert user.auth_source == "OIDC"


def test_oidc_redirects_stay_under_the_base_path(mongo_db: Database, oidc_settings: None) -> None:
    client = Client(SCRIPT_NAME="/panic")
    q = _start(client)
    id_token = _jwt(
        {
            "iss": "https://idp.example.com",
            "aud": "panic",
            "exp": time.time() + 300,
            "nonce": q["nonce"],
            "sub": "prefixed",
            "preferred_username": "pat.prefixed",
        }
    )
    with (
        override_settings(PANIC_BASE_PATH="/panic"),
        mock.patch.object(oidc, "_http_post_form", return_value={"id_token": id_token, "access_token": "at"}),
        mock.patch.object(oidc, "_http_get_json", return_value={"sub": "prefixed"}),
    ):
        resp = client.get(f"/auth/oidc/callback?state={q['state']}&code=xyz")
    assert resp.status_code == 302 and resp["Location"] == "/panic/lists"

    with override_settings(PANIC_BASE_PATH="/panic", PANIC_OIDC_ENABLED=False):
        resp = client.get("/auth/oidc/login")
    assert resp.status_code == 302 and resp["Location"] == "/panic/login"


def test_oidc_resignin_updates_only_display_name_and_last_login(mongo_db: Database, oidc_settings: None) -> None:
    client = Client()
    q = _start(client)
    id_token = _jwt(
        {
            "iss": "https://idp.example.com",
            "aud": "panic",
            "exp": time.time() + 300,
            "nonce": q["nonce"],
            "sub": "abc",
            "preferred_username": "dana.sso",
            "name": "Dana First",
        }
    )
    with mock.patch.object(oidc, "_http_post_form", return_value={"id_token": id_token}):
        client.get(f"/auth/oidc/callback?state={q['state']}&code=xyz")
    first = users_repo.get_user_by_username(mongo_db, "dana.sso")
    assert first is not None

    # An operator manually grants a permission through the (future) users page -- re-sign-in
    # must never clobber it.
    users_repo.update_user(mongo_db, first.id, first.version, permissions=[str(PermissionFlag.CAN_ADD_GLOBAL)])

    q2 = _start(client)
    id_token2 = _jwt(
        {
            "iss": "https://idp.example.com",
            "aud": "panic",
            "exp": time.time() + 300,
            "nonce": q2["nonce"],
            "sub": "abc",
            "preferred_username": "dana.sso",
            "name": "Dana Renamed",
        }
    )
    with mock.patch.object(oidc, "_http_post_form", return_value={"id_token": id_token2}):
        client.get(f"/auth/oidc/callback?state={q2['state']}&code=xyz2")

    second = users_repo.get_user_by_username(mongo_db, "dana.sso")
    assert second is not None
    assert second.display_name == "Dana Renamed"
    assert second.permissions == [PermissionFlag.CAN_ADD_GLOBAL]  # untouched by the re-sign-in


def test_oidc_rejects_bad_state_and_nonce(oidc_settings: None) -> None:
    client = Client()
    q = _start(client)
    assert client.get("/auth/oidc/callback?state=forged&code=xyz").status_code == 401
    q = _start(client)
    bad = _jwt({"iss": "https://idp.example.com", "aud": "panic", "exp": time.time() + 300, "nonce": "other"})
    with mock.patch.object(oidc, "_http_post_form", return_value={"id_token": bad}):
        assert client.get(f"/auth/oidc/callback?state={q['state']}&code=xyz").status_code == 401


class _FakeConn:
    """Minimal stand-in for ``ldap3.Connection``: service DN binds, user binds with 'pw'."""

    def __init__(self, server: Any, user: str | None = None, password: str | None = None, **_: Any) -> None:
        self.user, self.password, self.response = user, password, []

    def open(self) -> None: ...

    def start_tls(self) -> None: ...

    def unbind(self) -> None: ...

    def bind(self) -> bool:
        return self.user == "cn=svc,dc=example,dc=com" or self.password == "pw"

    def search(self, base: str, flt: str, *_: Any, **__: Any) -> None:
        self.response = [
            {
                "type": "searchResEntry",
                "dn": "uid=riley,ou=people,dc=example,dc=com",
                "attributes": {"uid": ["riley"], "displayName": "Riley Directory"},
            }
        ]


LDAP = {
    "PANIC_AUTH_LOCAL_ENABLED": False,
    "PANIC_LDAP_ENABLED": True,
    "PANIC_LDAP_URI": "ldaps://ldap.example.com",
    "PANIC_LDAP_BIND_DN": "cn=svc,dc=example,dc=com",
    "PANIC_LDAP_BIND_PASSWORD": "svcpw",
    "PANIC_LDAP_USER_BASE_DN": "ou=people,dc=example,dc=com",
    # Pinned: a developer .env may set its own filter, and the tests below assert on this one.
    "PANIC_LDAP_USER_FILTER": "(uid={username})",
}


def _login(client: Client, username: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login", {"username": username, "password": password}, content_type="application/json"
    )


def test_ldap_login_provisions_user_with_no_permissions(mongo_db: Database) -> None:
    with override_settings(**LDAP), mock.patch.object(ldap_auth, "Connection", _FakeConn):
        client = Client()
        assert _login(client, "riley", "nope").status_code == 401
        resp = _login(client, "riley", "pw")
        assert resp.status_code == 200
        user = users_repo.get_user_by_username(mongo_db, "riley")
        assert user is not None
        assert user.permissions == []
        assert user.team_ids == []
        assert user.display_name == "Riley Directory"
        assert user.auth_source == "LDAP"


def test_ldap_filter_escaping() -> None:
    captured: list[str] = []

    def spy(self: _FakeConn, base: str, flt: str, *a: Any, **k: Any) -> None:
        captured.append(flt)
        self.response = []

    with (
        override_settings(**LDAP),
        mock.patch.object(ldap_auth, "Connection", _FakeConn),
        mock.patch.object(_FakeConn, "search", spy),
    ):
        assert ldap_auth.authenticate("ri*ley)(uid=*", "pw") is None
    assert captured == ["(uid=ri\\2aley\\29\\28uid=\\2a)"]

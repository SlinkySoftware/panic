"""Claim mapping, OIDC and LDAP adapters with mocked providers (T-S3-02)."""

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

from panic_common.claim_mapping import ClaimMappingConfig, map_claims, normalize_group
from panic_common.models import PermissionFlag
from panic_server.auth import ldap_auth, oidc
from panic_server.state import STORE

RBAC = {
    "PANIC_RBAC_ADMIN_GROUPS": ["panic-admins"],
    "PANIC_RBAC_GLOBAL_CONTRIB_GROUPS": ["panic-global"],
    "PANIC_RBAC_TEAM_CONTRIB_GROUPS": ["panic-team-contrib"],
    "PANIC_RBAC_TEAM_GROUP_MAP": ["network-engineers=NETOPS"],
    "PANIC_RBAC_TEAM_GROUP_PREFIX": "panic-team-",
}
OIDC = {
    "PANIC_AUTH_MODE": "session",
    "PANIC_DEV_SIMULATOR_ENABLED": False,
    "PANIC_OIDC_ENABLED": True,
    "PANIC_OIDC_ISSUER": "https://idp.example.com",
    "PANIC_OIDC_CLIENT_ID": "panic",
    "PANIC_OIDC_CLIENT_SECRET": "s3cret",
    "PANIC_OIDC_AUTHORIZE_URL": "https://idp.example.com/authorize",
    "PANIC_OIDC_TOKEN_URL": "https://idp.example.com/token",
    "PANIC_OIDC_USERINFO_URL": "https://idp.example.com/userinfo",
    "PANIC_OIDC_REDIRECT_URI": "https://panic.example.com/auth/oidc/callback",
    **RBAC,
}


def _team_codes() -> dict[str, str]:
    return {t.id: t.code.upper() for t in STORE.teams}


def test_claim_mapping_admin_contrib_and_teams() -> None:
    cfg = ClaimMappingConfig.build(
        admin_groups=["PANIC-Admins"],
        global_contrib_groups=["panic-global"],
        team_contrib_groups=["panic-team-contrib"],
        team_group_map=["network-engineers=NETOPS", "malformed"],
        team_group_prefix="panic-team-",
    )
    teams = STORE.teams
    codes = {t.code.upper() for t in teams}
    some_code = sorted(codes)[0]
    admin = map_claims(["cn=panic-admins,ou=groups,dc=example,dc=com"], cfg, teams)
    assert PermissionFlag.GLOBAL_ADMIN in admin.permissions
    contrib = map_claims(["panic-global", "panic-team-contrib", f"panic-team-{some_code.lower()}"], cfg, teams)
    assert contrib.permissions == [PermissionFlag.CAN_ADD_GLOBAL, PermissionFlag.CAN_ADD_TEAM]
    assert [_team_codes()[t] for t in contrib.team_ids] == [some_code]
    assert map_claims(["unrelated", "panic-team-nosuchteam"], cfg, teams).team_ids == []
    assert normalize_group(" Ops ") == "ops"


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


def test_oidc_flow_provisions_user_with_teams_and_rbac(oidc_settings: None) -> None:
    client = Client()
    q = _start(client)
    netops = next((t for t in STORE.teams if t.code.upper() == "NETOPS"), None)
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
    user = STORE.get_user_by_username("casey.sso")
    assert user is not None
    assert user.display_name == "Casey SSO"
    assert user.permissions == [PermissionFlag.CAN_ADD_GLOBAL]
    if netops is not None:
        assert user.team_ids == [netops.id]
    assert client.get("/api/v1/state").json()["user"]["username"] == "casey.sso"


def test_oidc_rejects_bad_state_and_nonce(oidc_settings: None) -> None:
    client = Client()
    q = _start(client)
    assert client.get("/auth/oidc/callback?state=forged&code=xyz").status_code == 401
    q = _start(client)
    bad = _jwt({"iss": "https://idp.example.com", "aud": "panic", "exp": time.time() + 300, "nonce": "other"})
    with mock.patch.object(oidc, "_http_post_form", return_value={"id_token": bad}):
        assert client.get(f"/auth/oidc/callback?state={q['state']}&code=xyz").status_code == 401
    assert client.get("/api/v1/state").status_code == 401


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
        if base.startswith("ou=people"):
            self.response = [
                {
                    "type": "searchResEntry",
                    "dn": "uid=riley,ou=people,dc=example,dc=com",
                    "attributes": {"uid": ["riley"], "displayName": "Riley Directory"},
                }
            ]
        else:
            assert "uid=riley" in flt
            self.response = [
                {
                    "type": "searchResEntry",
                    "dn": "cn=panic-admins,ou=groups,dc=example,dc=com",
                    "attributes": {"cn": ["panic-admins"]},
                }
            ]


LDAP = {
    "PANIC_AUTH_MODE": "session",
    "PANIC_DEV_SIMULATOR_ENABLED": False,
    "PANIC_AUTH_LOCAL_ENABLED": False,
    "PANIC_LDAP_ENABLED": True,
    "PANIC_LDAP_URI": "ldaps://ldap.example.com",
    "PANIC_LDAP_BIND_DN": "cn=svc,dc=example,dc=com",
    "PANIC_LDAP_BIND_PASSWORD": "svcpw",
    "PANIC_LDAP_USER_BASE_DN": "ou=people,dc=example,dc=com",
    "PANIC_LDAP_GROUP_BASE_DN": "ou=groups,dc=example,dc=com",
    **RBAC,
}


def test_ldap_login_provisions_admin() -> None:
    with override_settings(**LDAP), mock.patch.object(ldap_auth, "Connection", _FakeConn):
        client = Client()
        assert client.post("/login", {"username": "riley", "password": "nope"}).status_code == 401
        resp = client.post("/login", {"username": "riley", "password": "pw"})
        assert resp.status_code == 302
        user = STORE.get_user_by_username("riley")
        assert user is not None and PermissionFlag.GLOBAL_ADMIN in user.permissions
        assert user.display_name == "Riley Directory"


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

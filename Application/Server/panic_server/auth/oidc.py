"""OIDC Authorization Code flow (with PKCE, ``state`` and ``nonce``) adapter.

The ID token is received directly from the token endpoint over TLS using the client secret, so
per OIDC Core §3.1.3.7 the TLS server validation substitutes for signature checking; ``iss``,
``aud``, ``exp`` and ``nonce`` are still verified. Claims from the userinfo endpoint (when
configured) are merged over the ID token claims.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from django.conf import settings

SESSION_KEY = "panic_oidc_flow"


class OidcError(Exception):
    """Raised for any OIDC protocol or provider failure (message is safe to log, not to display)."""


def _http_get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    resp = httpx.get(url, headers=headers or {}, timeout=settings.PANIC_OIDC_TIMEOUT_S)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise OidcError(f"non-object JSON from {url}")
    return data


def _http_post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    resp = httpx.post(
        url,
        data=data,
        auth=(settings.PANIC_OIDC_CLIENT_ID, settings.PANIC_OIDC_CLIENT_SECRET),
        headers={"Accept": "application/json"},
        timeout=settings.PANIC_OIDC_TIMEOUT_S,
    )
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        raise OidcError("non-object JSON from token endpoint")
    return body


_discovery_cache: dict[str, dict[str, Any]] = {}


def endpoints() -> dict[str, str]:
    """Return authorize/token/userinfo URLs, using explicit settings or issuer discovery."""
    out = {
        "authorization_endpoint": settings.PANIC_OIDC_AUTHORIZE_URL,
        "token_endpoint": settings.PANIC_OIDC_TOKEN_URL,
        "userinfo_endpoint": settings.PANIC_OIDC_USERINFO_URL,
    }
    if (not out["authorization_endpoint"] or not out["token_endpoint"]) and settings.PANIC_OIDC_ISSUER:
        issuer = settings.PANIC_OIDC_ISSUER.rstrip("/")
        if issuer not in _discovery_cache:
            _discovery_cache[issuer] = _http_get_json(f"{issuer}/.well-known/openid-configuration")
        disc = _discovery_cache[issuer]
        for key in out:
            out[key] = out[key] or str(disc.get(key, ""))
    if not out["authorization_endpoint"] or not out["token_endpoint"]:
        raise OidcError("OIDC endpoints are not configured")
    return out


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_authorization_url(session: Any, next_url: str) -> str:
    """Create a fresh flow (state, nonce, PKCE verifier) in ``session`` and return the IdP redirect URL."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    session[SESSION_KEY] = {"state": state, "nonce": nonce, "verifier": verifier, "next": next_url}
    params = {
        "response_type": "code",
        "client_id": settings.PANIC_OIDC_CLIENT_ID,
        "redirect_uri": settings.PANIC_OIDC_REDIRECT_URI,
        "scope": settings.PANIC_OIDC_SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
    }
    return f"{endpoints()['authorization_endpoint']}?{urlencode(params)}"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload_b64 = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    except (IndexError, ValueError) as e:
        raise OidcError("malformed id_token") from e
    if not isinstance(payload, dict):
        raise OidcError("malformed id_token payload")
    return payload


def _validate_id_token(claims: dict[str, Any], nonce: str) -> None:
    issuer = settings.PANIC_OIDC_ISSUER.rstrip("/")
    if issuer and str(claims.get("iss", "")).rstrip("/") != issuer:
        raise OidcError("id_token issuer mismatch")
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if settings.PANIC_OIDC_CLIENT_ID not in audiences:
        raise OidcError("id_token audience mismatch")
    if float(claims.get("exp", 0)) < time.time() - 60:
        raise OidcError("id_token expired")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OidcError("id_token nonce mismatch")


def complete_flow(session: Any, params: dict[str, str]) -> tuple[dict[str, Any], str]:
    """Validate the callback, exchange the code, and return ``(claims, next_url)``."""
    flow = session.pop(SESSION_KEY, None)
    if not isinstance(flow, dict):
        raise OidcError("no OIDC flow in progress")
    if params.get("error"):
        raise OidcError(f"provider returned error {params.get('error')!r}")
    if not secrets.compare_digest(params.get("state", ""), flow["state"]):
        raise OidcError("state mismatch")
    code = params.get("code", "")
    if not code:
        raise OidcError("missing authorization code")
    urls = endpoints()
    try:
        tokens = _http_post_form(
            urls["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.PANIC_OIDC_REDIRECT_URI,
                "code_verifier": flow["verifier"],
            },
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("token response has no id_token")
        claims = _decode_jwt_payload(id_token)
        _validate_id_token(claims, flow["nonce"])
        access_token = tokens.get("access_token")
        if urls["userinfo_endpoint"] and isinstance(access_token, str):
            userinfo = _http_get_json(urls["userinfo_endpoint"], {"Authorization": f"Bearer {access_token}"})
            if userinfo.get("sub") not in (None, claims.get("sub")):
                raise OidcError("userinfo subject mismatch")
            claims = {**claims, **userinfo}
    except httpx.HTTPError as e:
        raise OidcError(f"provider request failed: {type(e).__name__}") from e
    return claims, str(flow.get("next") or "/")


#: Claim holding group/role names, read for the IdP adapter's own convenience only -- nothing
#: maps it to PANIC RBAC/teams (ADR-0001 decision 11), so this is not configurable, just the
#: conventional OIDC claim name.
_GROUPS_CLAIM = "groups"


def identity_from_claims(claims: dict[str, Any]) -> tuple[str, str, list[str]]:
    """Return ``(username, display_name, groups)`` using the configured claim names.

    ``groups`` is returned for API/adapter symmetry with LDAP but is never mapped to PANIC
    permissions or teams (ADR-0001 decision 11): external identity is for authentication only.
    """
    username = str(claims.get(settings.PANIC_OIDC_USERNAME_CLAIM) or "")
    display = str(claims.get(settings.PANIC_OIDC_DISPLAY_NAME_CLAIM) or username)
    raw_groups = claims.get(_GROUPS_CLAIM) or []
    if isinstance(raw_groups, str):
        raw_groups = [g for g in raw_groups.replace(",", " ").split() if g]
    groups = [str(g) for g in raw_groups] if isinstance(raw_groups, list) else []
    return username, display, groups

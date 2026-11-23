"""The authorization matrix (AR-2.8): every route under ``panic_server.api.urls`` declares one
of ``public``, ``authenticated`` or ``admin``, and each tier behaves correctly for an anonymous
caller, a plain signed-in user, and a Global Admin.

:class:`panic_server.api.permissions.IsGlobalAdmin` is also exercised directly (unit-level)
alongside the live walk of the real routes, so the tier's own plain/admin behaviour is proven
independently of any one path.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from pymongo.database import Database

from panic_common.models import PermissionFlag
from panic_server.api import urls as api_urls
from panic_server.api.permissions import (
    TIERS,
    DenyAll,
    IsAuthenticated,
    IsGlobalAdmin,
    IsPublic,
    tier_of_method,
)
from panic_server.context import SESSION_USER_KEY
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]

#: Dummy path converters for dynamic routes, so every pattern resolves to a concrete URL.
_SAMPLE_KWARGS: dict[str, dict[str, str]] = {
    "ui-dashboard": {"dashboard_id": "does-not-exist"},
    "launch-rdp": {"item_id": "does-not-exist"},
    "dashboard-detail": {"dashboard_id": "does-not-exist"},
    "dashboard-layout": {"dashboard_id": "does-not-exist"},
    "me-menu": {"dashboard_id": "does-not-exist"},
    "catalog-detail": {"item_id": "does-not-exist"},
    "list-detail": {"list_id": "does-not-exist"},
    "site-detail": {"site_id": "does-not-exist"},
    "team-detail": {"team_id": "does-not-exist"},
    "team-members": {"team_id": "does-not-exist"},
    "zone-detail": {"zone_id": "does-not-exist"},
    "user-detail": {"user_id": "does-not-exist"},
    "orphan-assign": {"kind": "catalog", "item_id": "does-not-exist"},
}


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)


def _unique(prefix: str) -> str:
    """Each test re-invokes these fixtures (function-scoped, deliberately -- some tests mutate
    the user), so a fixed username would collide with ``users.username_unique`` across the many
    calls within one test session."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def plain_user(mongo_db: Database) -> Any:
    username = _unique("matrix-plain")
    return users_repo.create_user(
        mongo_db, username=username, display_name="Matrix Plain", default_remote_user=username
    )


@pytest.fixture
def admin_user(mongo_db: Database) -> Any:
    username = _unique("matrix-admin")
    return users_repo.create_user(
        mongo_db,
        username=username,
        display_name="Matrix Admin",
        default_remote_user=username,
        permissions=[str(PermissionFlag.GLOBAL_ADMIN)],
    )


def _client_as(user_id: str | None) -> Client:
    """A test ``Client`` with ``SESSION_USER_KEY`` pre-seeded (no need to exercise /auth/login
    itself here; that is ``tests/test_auth.py``'s job)."""
    client = Client()
    if user_id is not None:
        session = client.session
        session[SESSION_USER_KEY] = user_id
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    return client


def _routes() -> list[tuple[str, str, str | None]]:
    """``(url_path, http_method, tier)`` for every ``(route, method)`` pair in
    ``panic_server.api.urls`` -- every declared method, not just one arbitrary one: there are
    mixed-tier routes (e.g. ``GET /sites`` is "A", ``POST /sites`` is "G", same path),
    so the tier can depend on the method (:func:`tier_of_method`)."""
    routes = []
    for pattern in api_urls.urlpatterns:
        view = pattern.callback
        cls = view.cls
        methods = [m for m in cls.http_method_names if m != "options"]
        name = pattern.name
        path = reverse(name, kwargs=_SAMPLE_KWARGS.get(name, {}))
        for method in methods:
            routes.append((path, method, tier_of_method(cls.permission_classes, method)))
    return routes


def test_every_route_declares_a_tier() -> None:
    for path, _method, tier in _routes():
        assert tier in TIERS, f"{path!r} does not declare one of {sorted(TIERS)}"


def test_anonymous_gets_401_on_authenticated_routes_and_not_401_on_public_routes() -> None:
    for path, method, tier in _routes():
        # A fresh client per route: logout mutates the session, and reusing one client across
        # the whole walk would let that leak into later iterations' auth state.
        resp = getattr(_client_as(None), method)(path)
        if tier == "public":
            assert resp.status_code != 401, f"public {method.upper()} {path} unexpectedly 401'd"
        else:
            assert resp.status_code == 401, f"anonymous {method.upper()} {path} got {resp.status_code}, want 401"
            assert resp.json()["error_code"] == "UNAUTHENTICATED"


def test_plain_user_never_gets_401_on_authenticated_routes(plain_user: Any) -> None:
    for path, method, tier in _routes():
        if tier != "authenticated":
            continue
        resp = getattr(_client_as(plain_user.id), method)(path)
        # Past the auth layer: a missing/invisible resource is 404, a validation gap is 400/204,
        # but never an authz failure for a route this tier exists to allow.
        assert resp.status_code not in (401, 403), f"plain user {method.upper()} {path} got {resp.status_code}"


def test_admin_succeeds_on_every_route(admin_user: Any) -> None:
    for path, method, _tier in _routes():
        resp = getattr(_client_as(admin_user.id), method)(path)
        assert resp.status_code not in (401, 403), f"admin {method.upper()} {path} got {resp.status_code}"


# ---------------------------------------------------------------- IsGlobalAdmin (unit-level)
#
# The class's own plain/admin behaviour is proven directly, not only against a live URL.


def _fake_request(user: Any) -> SimpleNamespace:
    return SimpleNamespace(user=user)


def test_is_global_admin_denies_plain_denies_anonymous_allows_admin(plain_user: Any, admin_user: Any) -> None:
    perm = IsGlobalAdmin()
    assert perm.has_permission(_fake_request(None), None) is False
    assert perm.has_permission(_fake_request(plain_user), None) is False
    assert perm.has_permission(_fake_request(admin_user), None) is True


def test_is_authenticated_and_is_public_and_deny_all() -> None:
    assert IsPublic().has_permission(_fake_request(None), None) is True
    assert IsAuthenticated().has_permission(_fake_request(None), None) is False
    assert IsAuthenticated().has_permission(_fake_request(object()), None) is True
    assert DenyAll().has_permission(_fake_request(object()), None) is False

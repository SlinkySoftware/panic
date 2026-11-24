"""Super admin role: the bootstrap admin is always one; the role is invisible to everyone else and
regular admins can neither grant it, remove it, nor edit the bootstrap admin (auth/roles.py)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.test import Client, override_settings
from pymongo.database import Database

from panic_common.models import PermissionFlag
from panic_server.auth import backends
from panic_server.auth.roles import is_bootstrap_admin, is_super_admin
from panic_server.context import SESSION_USER_KEY, SESSION_VIEW_AS_KEY
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]

SUPER = str(PermissionFlag.SUPER_ADMIN)
ADMIN = str(PermissionFlag.GLOBAL_ADMIN)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _client_as(user_id: str, view_as: str | None = None) -> Client:
    client = Client()
    session = client.session
    session[SESSION_USER_KEY] = user_id
    if view_as:
        session[SESSION_VIEW_AS_KEY] = view_as
    session.save()
    client.cookies[django_settings.SESSION_COOKIE_NAME] = session.session_key
    return client


def _patch(client: Client, user_id: str, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/v1/users/{user_id}", json.dumps(body), content_type="application/json")


def _user(db: Database, prefix: str, perms: list[str], auth_source: str = "LDAP") -> Any:
    name = _unique(prefix)
    return users_repo.create_user(
        db, username=name, display_name=name, default_remote_user=name, permissions=perms, auth_source=auth_source
    )


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)


@pytest.fixture
def people(mongo_db: Database) -> dict[str, Any]:
    """A super admin, a regular admin, a plain user and the bootstrap admin (LOCAL, as
    ``ensure_bootstrap_admin`` leaves it), with ``PANIC_BOOTSTRAP_ADMIN_USER`` pointing at it."""
    boot_name = _unique("boot")
    boot = users_repo.create_user(
        mongo_db, username=boot_name, display_name="Boot", default_remote_user=boot_name, permissions=[SUPER, ADMIN]
    )
    with override_settings(PANIC_BOOTSTRAP_ADMIN_USER=boot_name):
        yield {
            "super": _user(mongo_db, "sa", [SUPER, ADMIN]),
            "admin": _user(mongo_db, "ga", [ADMIN]),
            "plain": _user(mongo_db, "pl", []),
            "boot": boot,
        }


# ---------------------------------------------------------------- bootstrap admin


def test_bootstrap_admin_is_super_admin_without_the_flag(mongo_db: Database) -> None:
    name = _unique("boot-noflag")
    boot = users_repo.create_user(
        mongo_db, username=name, display_name=name, default_remote_user=name, permissions=[ADMIN]
    )
    with override_settings(PANIC_BOOTSTRAP_ADMIN_USER=name):
        assert SUPER not in boot.permissions
        assert is_bootstrap_admin(boot) and is_super_admin(boot)
        body = _client_as(boot.id).get("/api/v1/ui/bootstrap").json()
        assert body["permissions"]["super_admin"] is True


def test_an_ldap_user_is_never_the_bootstrap_admin(people: dict[str, Any]) -> None:
    assert not is_bootstrap_admin(people["super"])


def test_bootstrap_admin_must_be_a_local_account(mongo_db: Database) -> None:
    name = _unique("ldap-boot")
    ldap_user = _user(mongo_db, "x", [ADMIN], auth_source="LDAP").model_copy(update={"username": name})
    with override_settings(PANIC_BOOTSTRAP_ADMIN_USER=name):
        assert not is_bootstrap_admin(ldap_user)


def test_ensure_bootstrap_admin_grants_super_admin(mongo_db: Database) -> None:
    name = _unique("bootcfg")
    users_repo.create_user(mongo_db, username=name, display_name=name, default_remote_user=name, permissions=[ADMIN])
    with override_settings(
        PANIC_BOOTSTRAP_ADMIN_USER=name, PANIC_BOOTSTRAP_ADMIN_PASSWORD="pw-boot-test", PANIC_AUTH_LOCAL_ENABLED=True
    ):
        user = backends.ensure_bootstrap_admin()
    assert user is not None
    assert {SUPER, ADMIN} <= set(users_repo.get_user_by_username(mongo_db, name).permissions)


# ---------------------------------------------------------------- what a regular admin sees


def test_regular_admin_never_sees_super_admin(people: dict[str, Any]) -> None:
    client = _client_as(people["admin"].id)
    assert all(SUPER not in r["permissions"] for r in client.get("/api/v1/users").json()["results"])
    rows = client.get(f"/api/v1/users?q={people['super'].username}").json()["results"]
    assert [r["permissions"] for r in rows] == [[ADMIN]]  # looks like a plain admin
    detail = client.get(f"/api/v1/users/{people['super'].id}").json()
    assert SUPER not in detail["permissions"]
    assert client.get("/api/v1/users?permission=SUPER_ADMIN").json()["results"] == []
    assert client.get("/api/v1/ui/bootstrap").json()["permissions"]["super_admin"] is False


def test_rows_flag_the_bootstrap_admin_and_who_may_edit_it(people: dict[str, Any]) -> None:
    boot_id = people["boot"].id
    as_admin = _client_as(people["admin"].id).get(f"/api/v1/users/{boot_id}").json()
    assert as_admin["bootstrap_admin"] is True and as_admin["can_edit"] is False
    as_super = _client_as(people["super"].id).get(f"/api/v1/users/{boot_id}").json()
    assert as_super["bootstrap_admin"] is True and as_super["can_edit"] is True
    other = _client_as(people["admin"].id).get(f"/api/v1/users/{people['plain'].id}").json()
    assert other["bootstrap_admin"] is False and other["can_edit"] is True


def test_regular_admin_edit_keeps_a_hidden_super_admin(mongo_db: Database, people: dict[str, Any]) -> None:
    target = people["super"]
    resp = _patch(_client_as(people["admin"].id), target.id, {"permissions": [ADMIN, "CAN_ADD_TEAM"]})
    assert resp.status_code == 200
    assert SUPER not in resp.json()["permissions"]  # still hidden in the response
    assert {SUPER, ADMIN, "CAN_ADD_TEAM"} <= set(users_repo.get_user(mongo_db, target.id).permissions)


def test_regular_admin_cannot_grant_super_admin(people: dict[str, Any]) -> None:
    client = _client_as(people["admin"].id)
    assert _patch(client, people["plain"].id, {"permissions": [SUPER, ADMIN]}).status_code == 403
    created = client.post(
        "/api/v1/users",
        json.dumps({"username": _unique("new"), "permissions": [SUPER]}),
        content_type="application/json",
    )
    assert created.status_code == 403


def test_regular_admin_cannot_edit_the_bootstrap_admin(people: dict[str, Any]) -> None:
    resp = _patch(_client_as(people["admin"].id), people["boot"].id, {"display_name": "Renamed"})
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "PROTECTED_RESOURCE"


# ---------------------------------------------------------------- what a super admin may do


def test_super_admin_sees_and_grants_super_admin(mongo_db: Database, people: dict[str, Any]) -> None:
    client = _client_as(people["super"].id)
    detail = client.get(f"/api/v1/users/{people['super'].id}").json()
    assert SUPER in detail["permissions"]
    resp = _patch(client, people["plain"].id, {"permissions": [SUPER]})
    assert resp.status_code == 200
    assert {SUPER, ADMIN} <= set(resp.json()["permissions"])  # GLOBAL_ADMIN implied
    revoked = _patch(client, people["plain"].id, {"permissions": [ADMIN]})
    assert revoked.status_code == 200 and SUPER not in users_repo.get_user(mongo_db, people["plain"].id).permissions


def test_super_admin_edits_bootstrap_but_cannot_disable_or_demote_it(people: dict[str, Any]) -> None:
    client = _client_as(people["super"].id)
    boot_id = people["boot"].id
    renamed = _patch(client, boot_id, {"display_name": "Bootstrap (renamed)"})
    assert renamed.status_code == 200 and renamed.json()["display_name"] == "Bootstrap (renamed)"
    for body in ({"disabled": True}, {"permissions": ["CAN_ADD_TEAM"]}, {"permissions": [ADMIN]}):
        resp = _patch(client, boot_id, body)
        assert resp.status_code == 409, body
        assert resp.json()["error_code"] == "PROTECTED_RESOURCE"


def test_bootstrap_admin_editable_before_its_next_sign_in_stores_the_flag(
    mongo_db: Database, people: dict[str, Any]
) -> None:
    """Right after an upgrade the bootstrap admin may still lack SUPER_ADMIN in the database."""
    name = _unique("boot-upgraded")
    boot = users_repo.create_user(
        mongo_db, username=name, display_name=name, default_remote_user=name, permissions=[ADMIN]
    )
    with override_settings(PANIC_BOOTSTRAP_ADMIN_USER=name):
        resp = _patch(_client_as(people["super"].id), boot.id, {"display_name": "Renamed after upgrade"})
    assert resp.status_code == 200, resp.content


# ---------------------------------------------------------------- View As


def test_regular_admin_viewing_as_super_admin_gets_no_super_powers(people: dict[str, Any]) -> None:
    client = _client_as(people["admin"].id, view_as=people["super"].id)
    body = client.get("/api/v1/ui/bootstrap").json()
    assert body["view_as"]["id"] == people["super"].id
    assert body["permissions"]["super_admin"] is False
    rows = client.get(f"/api/v1/users?q={people['super'].username}").json()["results"]
    assert [r["permissions"] for r in rows] == [[ADMIN]]
    assert client.get("/api/v1/admin/config/export").status_code == 403


def test_config_endpoints_are_super_admin_only(people: dict[str, Any]) -> None:
    for who in ("plain", "admin"):
        client = _client_as(people[who].id)
        assert client.get("/api/v1/admin/config/export").status_code == 403, who
        for path in ("/api/v1/admin/config/import/preview", "/api/v1/admin/config/import"):
            assert client.post(path, "{}", content_type="application/json").status_code == 403, (who, path)
    assert _client_as(people["super"].id).get("/api/v1/admin/config/export").status_code == 200


def test_config_import_is_blocked_during_view_as(people: dict[str, Any]) -> None:
    # A super admin viewing as another super admin keeps the role, but View As is read-only.
    other = people["boot"]
    client = _client_as(people["super"].id, view_as=other.id)
    doc = _client_as(people["super"].id).get("/api/v1/admin/config/export").json()
    preview = client.post("/api/v1/admin/config/import/preview", json.dumps(doc), content_type="application/json")
    assert preview.status_code == 200  # a preview writes nothing
    resp = client.post(
        "/api/v1/admin/config/import",
        json.dumps({"document": doc, "plan_digest": preview.json()["plan_digest"]}),
        content_type="application/json",
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "VIEW_AS_READ_ONLY"

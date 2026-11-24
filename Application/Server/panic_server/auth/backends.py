"""Local (bootstrap admin) authentication and external-identity provisioning.

External identity (OIDC/LDAP) is for authentication only (ADR-0001 decision 11):
``provision_external_user`` never derives ``permissions``/``team_ids`` from directory groups.
A first external sign-in provisions the user with no permissions and no teams; later sign-ins
update only ``display_name`` and ``last_login_at``. Disabled users cannot sign in (AR-2.11):
every path here refuses them.
"""

from __future__ import annotations

import re
from functools import cache

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password

from panic_common.models import PermissionFlag, UserAccount
from panic_server.store.client import get_db
from panic_server.store.errors import NotFound
from panic_server.store.repos import users as users_repo


# Constant-time dummy check for unknown users so response timing does not reveal valid usernames.
@cache
def _dummy_hash() -> str:
    return make_password("panic-dummy-password")


_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@\-]{1,150}$")


def valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username))


def ensure_bootstrap_admin() -> UserAccount | None:
    """Create or update the local bootstrap admin (Super Admin) from ``PANIC_BOOTSTRAP_ADMIN_*``."""
    username = settings.PANIC_BOOTSTRAP_ADMIN_USER
    password = settings.PANIC_BOOTSTRAP_ADMIN_PASSWORD
    if not (settings.PANIC_AUTH_LOCAL_ENABLED and username and password and valid_username(username)):
        return None
    admin_perms = [
        PermissionFlag.SUPER_ADMIN,
        PermissionFlag.GLOBAL_ADMIN,
        PermissionFlag.CAN_ADD_GLOBAL,
        PermissionFlag.CAN_ADD_TEAM,
    ]
    db = get_db()
    user = users_repo.get_user_by_username(db, username)
    if user is None:
        user = users_repo.create_user(
            db,
            username=username,
            display_name=f"{username} (Bootstrap Admin)",
            default_remote_user=username,
            permissions=[str(p) for p in admin_perms],
        )
    elif not {PermissionFlag.SUPER_ADMIN, PermissionFlag.GLOBAL_ADMIN} <= set(user.permissions):
        merged = list(dict.fromkeys([*map(str, user.permissions), *map(str, admin_perms)]))
        user = users_repo.update_user(db, user.id, user.version, permissions=merged)
    stored_hash = users_repo.get_password_hash(db, username)
    if not stored_hash or not check_password(password, stored_hash):
        users_repo.set_password_hash(db, username, make_password(password), auth_source="LOCAL")
    return user


def authenticate_local(username: str, password: str) -> UserAccount | None:
    """Verify a local password. Only accounts with a stored hash (``auth_source=LOCAL``) can sign in."""
    if not settings.PANIC_AUTH_LOCAL_ENABLED or not valid_username(username) or not password:
        return None
    ensure_bootstrap_admin()
    db = get_db()
    stored = users_repo.get_password_hash(db, username)
    if not stored:
        check_password(password, _dummy_hash())
        return None
    if not check_password(password, stored):
        return None
    user = users_repo.get_user_by_username(db, username)
    if user is None or user.disabled:
        return None
    return user


def provision_external_user(
    username: str, display_name: str, groups: list[str], auth_source: str
) -> UserAccount | None:
    """Create or update a user from an external IdP (OIDC/LDAP). ``groups`` is accepted for the
    adapters' convenience but is never mapped to RBAC/teams here (ADR-0001 decision 11): that is
    exclusively a ``/settings/users`` concern.
    """
    if not valid_username(username):
        return None
    db = get_db()
    user = users_repo.get_user_by_username(db, username)
    if user is None:
        return users_repo.create_user(
            db,
            username=username,
            display_name=display_name or username,
            default_remote_user=username,
            auth_source=auth_source.upper(),
            permissions=[],
            team_ids=[],
        )
    if user.disabled:
        return None
    users_repo.touch_last_login(db, user.id, display_name=display_name or None)
    try:
        return users_repo.get_user(db, user.id)
    except NotFound:
        return None

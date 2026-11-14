"""Local (bootstrap admin) authentication and external-identity provisioning (T-S3-01 / T-S3-02).

All functions operate on the process ``STORE`` and must be called while holding ``STORE._lock``
(``PortalStoreMiddleware`` holds it for the whole request).
"""

from __future__ import annotations

import re
import uuid
from functools import cache

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password

from panic_common.claim_mapping import ClaimMappingConfig, map_claims
from panic_common.models import PermissionFlag, UserAccount
from panic_server.state import STORE


# Constant-time dummy check for unknown users so response timing does not reveal valid usernames.
@cache
def _dummy_hash() -> str:
    return make_password("panic-dummy-password")


_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@\-]{1,150}$")


def valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username))


def claim_mapping_config() -> ClaimMappingConfig:
    return ClaimMappingConfig.build(
        admin_groups=settings.PANIC_RBAC_ADMIN_GROUPS,
        global_contrib_groups=settings.PANIC_RBAC_GLOBAL_CONTRIB_GROUPS,
        team_contrib_groups=settings.PANIC_RBAC_TEAM_CONTRIB_GROUPS,
        team_group_map=settings.PANIC_RBAC_TEAM_GROUP_MAP,
        team_group_prefix=settings.PANIC_RBAC_TEAM_GROUP_PREFIX,
    )


def ensure_bootstrap_admin() -> UserAccount | None:
    """Create or update the local bootstrap Global Admin from ``PANIC_BOOTSTRAP_ADMIN_*``."""
    username = settings.PANIC_BOOTSTRAP_ADMIN_USER
    password = settings.PANIC_BOOTSTRAP_ADMIN_PASSWORD
    if not (settings.PANIC_AUTH_LOCAL_ENABLED and username and password and valid_username(username)):
        return None
    admin_perms = [PermissionFlag.GLOBAL_ADMIN, PermissionFlag.CAN_ADD_GLOBAL, PermissionFlag.CAN_ADD_TEAM]
    user = STORE.get_user_by_username(username)
    if user is None:
        user = UserAccount(
            id=f"usr-{uuid.uuid4().hex[:12]}",
            username=username,
            display_name=f"{username} (Bootstrap Admin)",
            default_remote_user=username,
            permissions=admin_perms,
        )
        STORE.save_user(user)
        STORE.record_audit(
            action="auth.bootstrap_admin.create",
            target_type="user_account",
            target_id=user.id,
            summary=f"Provisioned local bootstrap admin {username}",
            actor_username="system",
        )
    elif PermissionFlag.GLOBAL_ADMIN not in user.permissions:
        user.permissions = admin_perms
        STORE.save_user(user)
    if not check_password(password, STORE.get_user_password_hash(username)):
        STORE.set_user_password_hash(username, make_password(password), auth_source="local")
    return user


def authenticate_local(username: str, password: str) -> UserAccount | None:
    """Verify a local password. Only accounts with a stored hash (``auth_source=local``) can sign in."""
    if not settings.PANIC_AUTH_LOCAL_ENABLED or not valid_username(username) or not password:
        return None
    ensure_bootstrap_admin()
    stored = STORE.get_user_password_hash(username)
    if not stored:
        check_password(password, _dummy_hash())
        return None
    if not check_password(password, stored):
        return None
    return STORE.get_user_by_username(username)


def provision_external_user(
    username: str, display_name: str, groups: list[str], auth_source: str
) -> UserAccount | None:
    """Create or update a user from an external IdP, syncing RBAC flags and team membership."""
    if not valid_username(username):
        return None
    mapped = map_claims(groups, claim_mapping_config(), STORE.teams)
    user = STORE.get_user_by_username(username)
    if user is None:
        user = UserAccount(
            id=f"usr-{uuid.uuid4().hex[:12]}",
            username=username,
            display_name=display_name or username,
            default_remote_user=username,
        )
    user.display_name = display_name or user.display_name
    user.permissions = list(mapped.permissions)
    user.team_ids = list(mapped.team_ids)
    for team in STORE.teams:
        if team.id in mapped.team_ids and username not in team.members:
            team.members = [*team.members, username]
        elif team.id not in mapped.team_ids and username in team.members:
            team.members = [m for m in team.members if m != username]
    STORE.save_user(user)
    STORE.set_user_password_hash(username, "", auth_source=auth_source)
    STORE.record_audit(
        action="auth.provision",
        target_type="user_account",
        target_id=user.id,
        summary=f"Synchronised {auth_source} identity {username} (teams={len(user.team_ids)})",
        details={"permissions": [str(p) for p in user.permissions], "team_ids": user.team_ids},
        actor_username="system",
    )
    return user

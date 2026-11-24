"""Super admin: the role above Global Admin (config export/import, application settings).

The bootstrap admin (``PANIC_BOOTSTRAP_ADMIN_USER``, local account) is always a super admin and
can only be edited by super admins. The role is invisible to everyone else: for a viewer who is
not a super admin, ``SUPER_ADMIN`` is stripped from every permission list, so super admins look
like ordinary Global Admins. Super admins always hold ``GLOBAL_ADMIN`` as well.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings

from panic_common.models import AuthSource, PermissionFlag, UserAccount


def is_bootstrap_admin(user: UserAccount | None) -> bool:
    username = settings.PANIC_BOOTSTRAP_ADMIN_USER
    return bool(user and username and user.username == username and user.auth_source == AuthSource.LOCAL)


def is_super_admin(user: UserAccount | None) -> bool:
    return bool(user and (PermissionFlag.SUPER_ADMIN in user.permissions or is_bootstrap_admin(user)))


def sees_super_admin(real: UserAccount | None, effective: UserAccount | None) -> bool:
    """Whether a request may see or use the role: the real user *and* any View As subject are super
    admins (a Global Admin viewing as a super admin still sees super admins as plain admins)."""
    return is_super_admin(real) and is_super_admin(effective)


def visible_permissions(permissions: Iterable[str], viewer_is_super: bool) -> list[str]:
    return [str(p) for p in permissions if viewer_is_super or p != PermissionFlag.SUPER_ADMIN]


def with_implied(permissions: Iterable[str]) -> list[str]:
    """``SUPER_ADMIN`` implies ``GLOBAL_ADMIN``."""
    perms = [str(p) for p in permissions]
    if PermissionFlag.SUPER_ADMIN in perms and PermissionFlag.GLOBAL_ADMIN not in perms:
        perms.append(str(PermissionFlag.GLOBAL_ADMIN))
    return perms


__all__ = ["is_bootstrap_admin", "is_super_admin", "sees_super_admin", "visible_permissions", "with_implied"]

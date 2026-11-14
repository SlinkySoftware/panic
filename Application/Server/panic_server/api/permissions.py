"""The three access tiers every view must declare (AR-2.8): ``public``, ``authenticated``, ``admin``.

Each reads ``request.user`` -- set by :class:`panic_server.api.authentication.RequestContextAuthentication`
to the effective :class:`~panic_common.models.UserAccount` (``None`` when anonymous, since
``REST_FRAMEWORK["UNAUTHENTICATED_USER"] = None``). Permission checks never look at
``request.context`` directly, so there is exactly one DRF-facing notion of "who is this request".

:class:`DenyAll` is ``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]``: a view that forgets to
declare one of the three tiers below fails closed (403/401) instead of silently defaulting to
public, which is what makes ``tests/api/test_authz_matrix.py`` a meaningful check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rest_framework.permissions import BasePermission

from panic_common.models import PermissionFlag
from panic_common.rbac import has_permission

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView


class DenyAll(BasePermission):
    """The default for any view that does not explicitly set ``permission_classes`` (AR-2.8)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return False


class IsPublic(BasePermission):
    """No session required (API.md's ``P``)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return True


class IsAuthenticated(BasePermission):
    """Any signed-in caller -- real user or an active View As subject (API.md's ``A``)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.user is not None


class IsGlobalAdmin(BasePermission):
    """``GLOBAL_ADMIN`` on the effective user (API.md's ``G``)."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return user is not None and has_permission(user, PermissionFlag.GLOBAL_ADMIN)


#: ``tier name -> permission class``, used by the authz matrix test to label every route.
TIERS: dict[str, type[BasePermission]] = {
    "public": IsPublic,
    "authenticated": IsAuthenticated,
    "admin": IsGlobalAdmin,
}


def tier_of(permission_classes: tuple[Any, ...] | list[Any]) -> str | None:
    """The declared tier name for a view's ``permission_classes``, or ``None`` if none match."""
    for name, cls in TIERS.items():
        if cls in permission_classes:
            return name
    return None


__all__ = ["TIERS", "DenyAll", "IsAuthenticated", "IsGlobalAdmin", "IsPublic", "tier_of"]

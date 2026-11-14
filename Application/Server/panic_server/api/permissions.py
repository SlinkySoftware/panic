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

from rest_framework.permissions import SAFE_METHODS, BasePermission

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


class IsRealGlobalAdmin(BasePermission):
    """``GLOBAL_ADMIN`` on the **real** signed-in user, not the View As effective user (T-S6-07).

    ``request.user`` (and so :class:`IsGlobalAdmin`) is always the *effective* user
    (``RequestContextAuthentication``) -- the View As subject when View As is active. That is
    wrong for exactly one pair of endpoints: ``PUT``/``DELETE /api/v1/admin/view-as``. Starting
    View As is naturally real-user-only ("G (real user)", API.md §4.7); exiting it must stay
    available to the real admin *even while* ``effective_user`` (the subject being viewed as)
    lacks ``GLOBAL_ADMIN`` -- otherwise an admin viewing as an ordinary user could never click
    their own "Exit View As" button again. Both checks therefore read ``request.context.real_user``
    directly rather than ``request.user``.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        django_request = getattr(request, "_request", request)
        context = getattr(django_request, "context", None)
        real = getattr(context, "real_user", None)
        return real is not None and has_permission(real, PermissionFlag.GLOBAL_ADMIN)


class ReadAuthenticatedWriteAdmin(BasePermission):
    """Mixed-tier resource (T-S6-07): any signed-in user may read (``GET``/``HEAD``/``OPTIONS``,
    API.md's ``A``), but only a Global Admin may write (API.md's ``G``).

    Several API.md §4.7 collections share one URL for both tiers (e.g. ``GET /api/v1/sites`` is
    "A" while ``POST /api/v1/sites`` is "G") -- a single Django path can only resolve to one view,
    so the tier split has to happen inside one permission class rather than across two routes.
    :func:`tier_of_method` (not :func:`tier_of`, which only knows one tier per class) is how
    ``tests/api/test_authz_matrix.py`` labels each *method* of such a route correctly.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        if request.method in SAFE_METHODS:
            return IsAuthenticated().has_permission(request, view)
        return IsGlobalAdmin().has_permission(request, view)


#: ``tier name -> permission class (or classes)``, used by the authz matrix test to label every
#: route. ``admin`` accepts either ``IsGlobalAdmin`` (the common case) or ``IsRealGlobalAdmin``
#: (the View As start/exit pair, T-S6-07) -- both are "G" in API.md terms, just checked against a
#: different user.
TIERS: dict[str, type[BasePermission] | tuple[type[BasePermission], ...]] = {
    "public": IsPublic,
    "authenticated": IsAuthenticated,
    "admin": (IsGlobalAdmin, IsRealGlobalAdmin),
}


def tier_of(permission_classes: tuple[Any, ...] | list[Any]) -> str | None:
    """The declared tier name for a view's ``permission_classes``, or ``None`` if none match.

    Returns ``None`` for :class:`ReadAuthenticatedWriteAdmin` (and any other class not in
    :data:`TIERS`) -- callers that need to resolve a mixed-tier route's *per-method* tier must
    use :func:`tier_of_method` instead.
    """
    for name, classes in TIERS.items():
        candidates = classes if isinstance(classes, tuple) else (classes,)
        if any(c in permission_classes for c in candidates):
            return name
    return None


def tier_of_method(permission_classes: tuple[Any, ...] | list[Any], method: str) -> str | None:
    """Like :func:`tier_of`, but resolves :class:`ReadAuthenticatedWriteAdmin` per HTTP ``method``."""
    if ReadAuthenticatedWriteAdmin in permission_classes:
        return "authenticated" if method.upper() in {"GET", "HEAD", "OPTIONS"} else "admin"
    return tier_of(permission_classes)


__all__ = [
    "TIERS",
    "DenyAll",
    "IsAuthenticated",
    "IsGlobalAdmin",
    "IsPublic",
    "IsRealGlobalAdmin",
    "ReadAuthenticatedWriteAdmin",
    "tier_of",
    "tier_of_method",
]

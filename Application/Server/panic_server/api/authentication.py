"""Bridges ``request.context`` (the per-request identity) into DRF, plus CSRF enforcement.

Identity resolution itself already happened once per request, in
``panic_server.middleware.RequestContextMiddleware`` (before any DRF code runs). This
authentication class does no resolution of its own: it only hands DRF the already-resolved
effective user, so DRF's own ``request.user``/``permission_denied()`` machinery (which
distinguishes "never authenticated" -> 401 from "authenticated but forbidden" -> 403, AR-2.8)
works without re-implementing it.

DRF views are ``csrf_exempt`` at the Django-middleware level by construction (``APIView.as_view()``
wraps every view that way), so Django's ``CsrfViewMiddleware`` never checks them. CSRF protection
for ``/api/v1/...`` therefore has to be enforced here instead -- mirroring exactly how DRF's own
``SessionAuthentication.enforce_csrf`` does it, but reporting ``403 CSRF_FAILED`` (API.md §1/§3)
rather than DRF's generic ``PermissionDenied``.
"""

from __future__ import annotations

from rest_framework.authentication import BaseAuthentication, CSRFCheck
from rest_framework.request import Request

from panic_common.errors import ErrorCode
from panic_common.models import UserAccount
from panic_server.api.errors import ApiError

_CSRF_FAILED_DETAIL = "CSRF token missing or invalid. Reload the page."


class RequestContextAuthentication(BaseAuthentication):
    """``(request.context.effective_user, None)`` when a session identifies someone, else ``None``."""

    def authenticate(self, request: Request) -> tuple[UserAccount, None] | None:
        self._enforce_csrf(request)
        context = getattr(request, "context", None)
        if context is None or context.effective_user is None:
            return None
        return (context.effective_user, None)

    def authenticate_header(self, request: Request) -> str:
        # DRF's ``APIView.handle_exception`` silently coerces ``NotAuthenticated`` (401) to 403
        # whenever no authenticator supplies a ``WWW-Authenticate`` header (HTTP requires one on
        # a genuine 401). Supplying this is what keeps an anonymous request to an "authenticated"
        # route a real 401 UNAUTHENTICATED (API.md §1/§3), not a 403.
        return "Session"

    @staticmethod
    def _enforce_csrf(request: Request) -> None:
        # ``CSRFCheck`` (a ``CsrfViewMiddleware`` subclass used standalone, exactly as DRF's own
        # ``SessionAuthentication`` does) no-ops for safe methods and for an already-satisfied
        # cookie/header pair; it only ever returns a non-``None`` reason to reject.
        check = CSRFCheck(_dummy_get_response)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise ApiError(ErrorCode.CSRF_FAILED, _CSRF_FAILED_DETAIL, status_code=403)


def _dummy_get_response(request: Request) -> None:
    """``CsrfViewMiddleware`` requires a ``get_response`` callable it never actually calls here."""
    return None


__all__ = ["RequestContextAuthentication"]

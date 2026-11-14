"""Session authentication enforcement, using the already-resolved ``request.context`` (T-S6-04).

Identity resolution itself (who the session's user is, whether a View As target applies) lives
in ``panic_server.context`` so there is exactly one place that resolves "who is this session's
user" -- this middleware only enforces the result: reject anonymous/invalid sessions, and reject
sessions for users who turned out to be disabled (AR-2.11: disabled users' sessions are rejected).
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse

from panic_common.errors import ErrorCode
from panic_server.context import SESSION_USER_KEY, SESSION_VIEW_AS_KEY

#: "/login"/"/logout" are kept here even though T-S6-06 deletes those routes: without the
#: carve-out, an anonymous request to either (e.g. a stale bookmark or old frontend build) would
#: redirect to itself below (an infinite loop) instead of falling through to Django's URL
#: resolver and getting a clean 404 (``panic_server.api.errors.not_found_view``). "/api/v1/auth/"
#: is the real replacement contract (providers/csrf/login/logout; API.md §4.1) -- its own DRF
#: permission classes (public/authenticated) gate it correctly without this middleware's help.
PUBLIC_PREFIXES = (
    "/login",
    "/logout",
    "/auth/",
    "/api/v1/auth/",
    "/metrics",
    "/api/v1/health",
    "/api/v1/version",
)


class PanicAuthMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(PUBLIC_PREFIXES):
            return self.get_response(request)

        context = request.context
        if context.real_user is None:
            # Either no session, or the session names a user who no longer exists or is now
            # disabled (AR-2.11): either way the session is no longer valid.
            if request.session.get(SESSION_USER_KEY):
                request.session.flush()
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"error_code": ErrorCode.UNAUTHENTICATED, "detail": "Authentication required"}, status=401
                )
            return HttpResponseRedirect(f"/login?next={quote(request.get_full_path())}")

        request.panic_user = context.real_user
        request.panic_effective_user = context.effective_user

        response = self.get_response(request)

        # Re-read ``request.context``, not the ``context`` captured above: T-S6-07's View As
        # start/exit views (``services.view_as``) deliberately swap ``request.context`` for a
        # freshly rebuilt one *during* the view, after mutating the session's View As key. Using
        # the pre-view snapshot here would see the *old* (necessarily ``view_as_active=False``)
        # state on the very request that starts View As, and immediately pop the key straight
        # back out of the session this middleware is supposed to only be tidying up after the
        # fact (e.g. a View As target that went stale/disabled mid-session elsewhere).
        current_context = getattr(request, "context", context)
        if not current_context.view_as_active:
            request.session.pop(SESSION_VIEW_AS_KEY, None)
        return response

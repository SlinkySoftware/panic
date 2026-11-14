"""Session authentication middleware: binds the signed-in user (and Admin "View As") to the store."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse

from panic_common.errors import ErrorCode
from panic_common.rbac import can_use_view_as
from panic_server.auth.views import SESSION_USER_KEY, SESSION_VIEW_AS_KEY
from panic_server.state import STORE

PUBLIC_PREFIXES = ("/login", "/logout", "/auth/", "/static/", "/metrics", "/api/v1/health", "/api/v1/version")


class PanicAuthMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if settings.PANIC_AUTH_MODE != "session" or request.path.startswith(PUBLIC_PREFIXES):
            return self.get_response(request)

        uid = request.session.get(SESSION_USER_KEY)
        user = next((u for u in STORE.users if u.id == uid), None) if uid else None
        if user is None:
            if uid:
                request.session.flush()
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"error_code": ErrorCode.UNAUTHENTICATED, "detail": "Authentication required"}, status=401
                )
            return HttpResponseRedirect(f"/login?next={quote(request.get_full_path())}")

        STORE.simulation.active_user_id = user.id
        view_as = request.session.get(SESSION_VIEW_AS_KEY)
        STORE.simulation.view_as_user_id = view_as if view_as and can_use_view_as(user) else None
        request.panic_user = user

        response = self.get_response(request)

        if STORE.simulation.view_as_user_id:
            request.session[SESSION_VIEW_AS_KEY] = STORE.simulation.view_as_user_id
        else:
            request.session.pop(SESSION_VIEW_AS_KEY, None)
        return response

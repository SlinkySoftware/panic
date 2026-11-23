"""OIDC login/callback views, and the shared ``sign_in`` session-establishment helper.

Local sign-in is the JSON contract at ``/api/v1/auth/{providers,csrf,login,logout}``
(``panic_server.api.views.auth``), which reuses ``sign_in`` below for session establishment +
audit rather than duplicating it.
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from panic_common.models import UserAccount
from panic_server.auth import oidc
from panic_server.auth.backends import provision_external_user
from panic_server.context import SESSION_USER_KEY, SESSION_VIEW_AS_KEY
from panic_server.paths import app_path
from panic_server.store.client import get_db
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import users as users_repo

log = logging.getLogger("panic_server.auth")


def safe_next(request: HttpRequest, candidate: str | None) -> str:
    """A post-sign-in SPA route (``/lists``), without the URL prefix; ``/`` when unsafe or absent."""
    if candidate and candidate.startswith("/") and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate if not candidate.startswith(("/login", "/logout", "/auth/")) else "/"
    return "/"


def _client_ip(request: HttpRequest) -> str:
    return getattr(request, "client_ip", None) or request.META.get("REMOTE_ADDR", "unknown")


def _login_methods_json(request: HttpRequest, status: int = 200, **extra: object) -> JsonResponse:
    body: dict[str, object] = {
        "instance_name": settings.PANIC_INSTANCE_NAME,
        "password_enabled": settings.PANIC_AUTH_LOCAL_ENABLED or settings.PANIC_LDAP_ENABLED,
        "oidc_enabled": settings.PANIC_OIDC_ENABLED,
        "oidc_provider_name": settings.PANIC_OIDC_PROVIDER_NAME,
    }
    body.update(extra)
    return JsonResponse(body, status=status)


def sign_in(request: HttpRequest, user: UserAccount, method: str) -> None:
    """Establish the session for ``user`` and audit it. Shared by the OIDC callback below and
    ``panic_server.api.views.auth.login_view`` (API.md §4.1's ``POST /api/v1/auth/login``)."""
    request.session.cycle_key()
    request.session[SESSION_USER_KEY] = user.id
    request.session.pop(SESSION_VIEW_AS_KEY, None)
    db = get_db()
    users_repo.touch_last_login(db, user.id)
    audit_repo.append_audit(
        db,
        actor_username=user.username,
        action="auth.login",
        target_type="user_account",
        target_id=user.id,
        summary=f"{user.username} signed in ({method})",
        client_ip=_client_ip(request),
    )


@require_GET
def oidc_login_view(request: HttpRequest) -> HttpResponse:
    if not settings.PANIC_OIDC_ENABLED:
        return HttpResponseRedirect(app_path("/login"))
    try:
        url = oidc.build_authorization_url(request.session, safe_next(request, request.GET.get("next")))
    except (oidc.OidcError, httpx.HTTPError) as e:
        log.warning("OIDC login unavailable: %s", type(e).__name__)
        return _login_methods_json(request, status=503, error="Single sign-on is unavailable.")
    return HttpResponseRedirect(url)


@require_GET
def oidc_callback_view(request: HttpRequest) -> HttpResponse:
    if not settings.PANIC_OIDC_ENABLED:
        return HttpResponseRedirect(app_path("/login"))
    try:
        claims, next_url = oidc.complete_flow(request.session, request.GET.dict())
    except oidc.OidcError as e:
        log.warning("OIDC callback rejected: %s", e)
        return _login_methods_json(request, status=401, error="Single sign-on failed. Please try again.")
    username, display, groups = oidc.identity_from_claims(claims)
    user = provision_external_user(username, display, groups, "oidc")
    if user is None:
        return _login_methods_json(request, status=401, error="Single sign-on returned an unusable username.")
    sign_in(request, user, "oidc")
    return HttpResponseRedirect(app_path(safe_next(request, next_url)))

"""``/login``, ``/logout`` and OIDC callback views (T-S3-01 / T-S3-02)."""

from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from panic_common.models import UserAccount
from panic_server.auth import ldap_auth, oidc
from panic_server.auth.backends import authenticate_local, provision_external_user
from panic_server.state import STORE

log = logging.getLogger("panic_server.auth")

SESSION_USER_KEY = "panic_user_id"
SESSION_VIEW_AS_KEY = "panic_view_as_user_id"
_GENERIC_FAILURE = "Invalid username or password."


def safe_next(request: HttpRequest, candidate: str | None) -> str:
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate if not candidate.startswith(("/login", "/logout", "/auth/")) else "/"
    return "/"


def _render_login(request: HttpRequest, status: int = 200, **ctx: str) -> HttpResponse:
    context = {
        "instance_name": settings.PANIC_INSTANCE_NAME,
        "password_enabled": settings.PANIC_AUTH_LOCAL_ENABLED or settings.PANIC_LDAP_ENABLED,
        "oidc_enabled": settings.PANIC_OIDC_ENABLED,
        "oidc_provider_name": settings.PANIC_OIDC_PROVIDER_NAME,
        "next": ctx.get("next", "/"),
        "username": ctx.get("username", ""),
        "error": ctx.get("error", ""),
    }
    return render(request, "panic/login.html", context, status=status)


def sign_in(request: HttpRequest, user: UserAccount, method: str) -> None:
    request.session.cycle_key()
    request.session[SESSION_USER_KEY] = user.id
    request.session.pop(SESSION_VIEW_AS_KEY, None)
    STORE.simulation.active_user_id = user.id
    STORE.simulation.view_as_user_id = None
    STORE.record_audit(
        action="auth.login",
        target_type="user_account",
        target_id=user.id,
        summary=f"{user.username} signed in ({method})",
        actor_username=user.username,
    )


@csrf_protect
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if settings.PANIC_AUTH_MODE != "session":
        return HttpResponseRedirect("/")
    next_url = safe_next(request, request.POST.get("next") or request.GET.get("next"))
    if request.method == "GET":
        if request.session.get(SESSION_USER_KEY):
            return HttpResponseRedirect(next_url)
        return _render_login(request, next=next_url)

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user = authenticate_local(username, password)
    method = "local"
    if user is None and settings.PANIC_LDAP_ENABLED:
        try:
            identity = ldap_auth.authenticate(username, password)
        except ldap_auth.LdapError as e:
            log.warning("LDAP authentication unavailable: %s", e)
            return _render_login(
                request, status=503, next=next_url, username=username, error="Directory service unavailable."
            )
        if identity is not None:
            user = provision_external_user(identity.username, identity.display_name, identity.groups, "ldap")
            method = "ldap"
    if user is None:
        STORE.record_audit(
            action="auth.login_failed",
            target_type="user_account",
            target_id=username[:150] or "-",
            summary=f"Failed sign-in for {username[:150]!r}",
            actor_username="anonymous",
        )
        return _render_login(request, status=401, next=next_url, username=username, error=_GENERIC_FAILURE)
    sign_in(request, user, method)
    return HttpResponseRedirect(next_url)


@csrf_protect
@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    uid = request.session.get(SESSION_USER_KEY)
    user = next((u for u in STORE.users if u.id == uid), None)
    if user is not None:
        STORE.record_audit(
            action="auth.logout",
            target_type="user_account",
            target_id=user.id,
            summary=f"{user.username} signed out",
            actor_username=user.username,
        )
    request.session.flush()
    return HttpResponseRedirect("/login")


@require_GET
def oidc_login_view(request: HttpRequest) -> HttpResponse:
    if settings.PANIC_AUTH_MODE != "session" or not settings.PANIC_OIDC_ENABLED:
        return HttpResponseRedirect("/login")
    try:
        url = oidc.build_authorization_url(request.session, safe_next(request, request.GET.get("next")))
    except (oidc.OidcError, httpx.HTTPError) as e:
        log.warning("OIDC login unavailable: %s", type(e).__name__)
        return _render_login(request, status=503, error="Single sign-on is unavailable.")
    return HttpResponseRedirect(url)


@require_GET
def oidc_callback_view(request: HttpRequest) -> HttpResponse:
    if settings.PANIC_AUTH_MODE != "session" or not settings.PANIC_OIDC_ENABLED:
        return HttpResponseRedirect("/login")
    try:
        claims, next_url = oidc.complete_flow(request.session, request.GET.dict())
    except oidc.OidcError as e:
        log.warning("OIDC callback rejected: %s", e)
        return _render_login(request, status=401, error="Single sign-on failed. Please try again.")
    username, display, groups = oidc.identity_from_claims(claims)
    user = provision_external_user(username, display, groups, "oidc")
    if user is None:
        return _render_login(request, status=401, error="Single sign-on returned an unusable username.")
    sign_in(request, user, "oidc")
    return HttpResponseRedirect(safe_next(request, next_url))

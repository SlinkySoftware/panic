"""``/login``, ``/logout`` and OIDC callback views (T-S3-01/02, T-S6-04).

The old server-rendered ``panic/login.html`` template is gone along with ``templates/`` (the
whole SSR UI is deleted this task; see ``Documents/TASKS.md`` T-S6-04's "Transition" note). GET
``/login`` now returns a small JSON body describing which sign-in methods are available -- an
explicitly acknowledged stopgap ahead of the real JSON ``/auth/login`` contract (API.md), which a
later task (the web rewrite, T-S6-08/09) builds a UI against. POST ``/login`` and ``/logout``
keep working exactly as before otherwise.
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from panic_common.models import UserAccount
from panic_server.auth import ldap_auth, oidc
from panic_server.auth.backends import authenticate_local, provision_external_user
from panic_server.context import SESSION_USER_KEY, SESSION_VIEW_AS_KEY
from panic_server.store.client import get_db
from panic_server.store.errors import NotFound
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import users as users_repo

log = logging.getLogger("panic_server.auth")

_GENERIC_FAILURE = "Invalid username or password."


def safe_next(request: HttpRequest, candidate: str | None) -> str:
    if candidate and url_has_allowed_host_and_scheme(
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


@csrf_protect
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    next_url = safe_next(request, request.POST.get("next") or request.GET.get("next"))
    if request.method == "GET":
        if request.session.get(SESSION_USER_KEY):
            return HttpResponseRedirect(next_url)
        return _login_methods_json(request, next=next_url)

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user = authenticate_local(username, password)
    method = "local"
    if user is None and settings.PANIC_LDAP_ENABLED:
        try:
            identity = ldap_auth.authenticate(username, password)
        except ldap_auth.LdapError as e:
            log.warning("LDAP authentication unavailable: %s", e)
            return _login_methods_json(
                request, status=503, next=next_url, username=username, error="Directory service unavailable."
            )
        if identity is not None:
            user = provision_external_user(identity.username, identity.display_name, identity.groups, "ldap")
            method = "ldap"
    if user is None:
        audit_repo.append_audit(
            get_db(),
            actor_username="anonymous",
            action="auth.login_failed",
            target_type="user_account",
            target_id=username[:150] or "-",
            summary=f"Failed sign-in for {username[:150]!r}",
            client_ip=_client_ip(request),
        )
        return _login_methods_json(request, status=401, next=next_url, username=username, error=_GENERIC_FAILURE)
    sign_in(request, user, method)
    return HttpResponseRedirect(next_url)


@csrf_protect
@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    uid = request.session.get(SESSION_USER_KEY)
    if uid:
        db = get_db()
        try:
            user = users_repo.get_user(db, str(uid))
        except NotFound:
            user = None
        if user is not None:
            audit_repo.append_audit(
                db,
                actor_username=user.username,
                action="auth.logout",
                target_type="user_account",
                target_id=user.id,
                summary=f"{user.username} signed out",
                client_ip=_client_ip(request),
            )
    request.session.flush()
    return HttpResponseRedirect("/login")


@require_GET
def oidc_login_view(request: HttpRequest) -> HttpResponse:
    if not settings.PANIC_OIDC_ENABLED:
        return HttpResponseRedirect("/login")
    try:
        url = oidc.build_authorization_url(request.session, safe_next(request, request.GET.get("next")))
    except (oidc.OidcError, httpx.HTTPError) as e:
        log.warning("OIDC login unavailable: %s", type(e).__name__)
        return _login_methods_json(request, status=503, error="Single sign-on is unavailable.")
    return HttpResponseRedirect(url)


@require_GET
def oidc_callback_view(request: HttpRequest) -> HttpResponse:
    if not settings.PANIC_OIDC_ENABLED:
        return HttpResponseRedirect("/login")
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
    return HttpResponseRedirect(safe_next(request, next_url))

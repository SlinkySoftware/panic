"""``/api/v1/auth/...`` -- providers, CSRF, login, logout (API.md §4.1).

Supersedes the Stage 3-5 server-rendered ``/login``/``/logout`` views and their T-S6-04 JSON
stopgap (``panic_server.auth.views.login_view``/``logout_view``, deleted by this task -- see
``panic_server/auth/urls.py``'s module docstring). Password verification, LDAP and OIDC
machinery are untouched: this module only wires ``panic_server.auth.backends``/``ldap_auth``
into the new DRF surface and reuses ``panic_server.auth.views.sign_in`` for session
establishment + audit, exactly as the brief asks.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.middleware.csrf import get_token
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_common.errors import ErrorCode
from panic_server.api.errors import ApiError
from panic_server.api.permissions import IsAuthenticated, IsPublic
from panic_server.api.serializers import LoginRequestSerializer, LoginResponseSerializer, ProvidersResponseSerializer
from panic_server.auth import ldap_auth
from panic_server.auth.backends import authenticate_local, provision_external_user
from panic_server.auth.views import sign_in
from panic_server.services.bootstrap import build_profile
from panic_server.store.client import get_db
from panic_server.store.repos import audit as audit_repo

log = logging.getLogger("panic_server.api.auth")

_GENERIC_FAILURE = "Invalid username or password."


def _client_ip(django_request: object) -> str:
    context = getattr(django_request, "context", None)
    if context is not None:
        return str(context.client_ip)
    return str(getattr(django_request, "META", {}).get("REMOTE_ADDR", "unknown"))


@extend_schema(tags=["auth"], responses=ProvidersResponseSerializer)
@api_view(["GET"])
@permission_classes([IsPublic])
def providers_view(request: Request) -> Response:
    """``GET /api/v1/auth/providers``: which sign-in methods are available, for the login page."""
    return Response(
        {
            "instance_name": settings.PANIC_INSTANCE_NAME,
            "local_enabled": settings.PANIC_AUTH_LOCAL_ENABLED,
            "ldap_enabled": settings.PANIC_LDAP_ENABLED,
            "oidc": {"enabled": settings.PANIC_OIDC_ENABLED, "provider_name": settings.PANIC_OIDC_PROVIDER_NAME},
        }
    )


@extend_schema(tags=["auth"], responses={204: OpenApiResponse(description="CSRF cookie set/rotated.")})
@api_view(["GET"])
@permission_classes([IsPublic])
def csrf_view(request: Request) -> Response:
    """``GET /api/v1/auth/csrf``: sets/rotates the ``panic_csrftoken`` cookie."""
    get_token(request._request)
    return Response(status=204)


@extend_schema(tags=["auth"], request=LoginRequestSerializer, responses=LoginResponseSerializer)
@api_view(["POST"])
@permission_classes([IsPublic])
def login_view(request: Request) -> Response:
    """``POST /api/v1/auth/login``: local then LDAP; uniform ``401`` on any failure."""
    serializer = LoginRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    username = serializer.validated_data["username"].strip()
    password = serializer.validated_data["password"]
    django_request = request._request

    user = authenticate_local(username, password)
    method = "local"
    if user is None and settings.PANIC_LDAP_ENABLED:
        try:
            identity = ldap_auth.authenticate(username, password)
        except ldap_auth.LdapError as e:
            log.warning("LDAP authentication unavailable: %s", e)
            raise ApiError(ErrorCode.UNAUTHENTICATED, _GENERIC_FAILURE, status_code=401) from e
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
            client_ip=_client_ip(django_request),
        )
        raise ApiError(ErrorCode.UNAUTHENTICATED, _GENERIC_FAILURE, status_code=401)

    sign_in(django_request, user, method)
    return Response({"me": build_profile(user)})


@extend_schema(tags=["auth"], request=None, responses={204: OpenApiResponse(description="Session flushed.")})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    """``POST /api/v1/auth/logout``: flush the session, audited against the real signed-in user."""
    django_request = request._request
    context = django_request.context
    if context.real_user is not None:
        audit_repo.append_audit(
            get_db(),
            actor_username=context.real_user.username,
            action="auth.logout",
            target_type="user_account",
            target_id=context.real_user.id,
            summary=f"{context.real_user.username} signed out",
            client_ip=_client_ip(django_request),
        )
    django_request.session.flush()
    return Response(status=204)


__all__ = ["csrf_view", "login_view", "logout_view", "providers_view"]

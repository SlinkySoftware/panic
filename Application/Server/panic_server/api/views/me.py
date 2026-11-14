"""``/api/v1/me`` -- current user's profile, default dashboard and menu pins (API.md §4.4)."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_server.api.concurrency import expected_version, version_conflict
from panic_server.api.permissions import IsAuthenticated
from panic_server.services import profile as profile_service
from panic_server.services.view_as import assert_not_view_as
from panic_server.store.client import get_db
from panic_server.store.errors import VersionConflict
from panic_server.store.repos import users as users_repo


@extend_schema(tags=["me"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me_view(request: Request) -> Response:
    """``GET`` the effective user's own profile; ``PATCH`` writes the **real** user's (refused
    during View As)."""
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    assert effective is not None  # IsAuthenticated already guarantees this

    if request.method == "GET":
        return Response(profile_service.build_me(effective))

    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    db = get_db()
    version = expected_version(request, real.version, required=False)
    try:
        updated = profile_service.update_me(db, real, version, **request.data)
    except VersionConflict:
        current = users_repo.get_user(db, real.id)
        raise version_conflict(current.version) from None
    return Response(profile_service.build_me(updated))


@extend_schema(tags=["me"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def default_dashboard_view(request: Request) -> Response:
    """``PUT /api/v1/me/default-dashboard``: ``{"dashboard_id": "uuid" | null}``, must be visible."""
    django_request = request._request
    context = django_request.context
    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    db = get_db()
    dashboard_id = request.data.get("dashboard_id")
    version = expected_version(request, real.version, required=False)
    try:
        updated = profile_service.set_default_dashboard(db, real, version, dashboard_id)
    except VersionConflict:
        current = users_repo.get_user(db, real.id)
        raise version_conflict(current.version) from None
    return Response(profile_service.build_me(updated))


@extend_schema(
    tags=["me"], responses={204: OpenApiResponse(description="Pinned/unpinned.")}, request=OpenApiTypes.OBJECT
)
@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def menu_pin_view(request: Request, dashboard_id: str) -> Response:
    """``PUT`` pins ``dashboard_id`` to the real user's menu; ``DELETE`` unpins it."""
    django_request = request._request
    context = django_request.context
    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    db = get_db()
    version = expected_version(request, real.version, required=False)
    try:
        if request.method == "PUT":
            profile_service.pin_dashboard(db, real, version, dashboard_id)
        else:
            profile_service.unpin_dashboard(db, real, version, dashboard_id)
    except VersionConflict:
        current = users_repo.get_user(db, real.id)
        raise version_conflict(current.version) from None
    return Response(status=204)


__all__ = ["default_dashboard_view", "me_view", "menu_pin_view"]

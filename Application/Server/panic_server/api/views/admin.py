"""``/api/v1/{sites,teams,zones,users,admin/orphans,admin/view-as,settings}`` (API.md §4.7).

Every mutation here is refused during View As (``services.view_as.assert_not_view_as``) --
including admin actions: an admin tier view's ``IsGlobalAdmin`` permission already blocks a
View-As-as-a-non-admin caller, but an admin View-As-ing *another* admin would otherwise slip
through, so the guard is still called explicitly rather than relying on that incidental overlap.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_server.api.concurrency import expected_version, version_conflict
from panic_server.api.pagination import PageEnvelopePagination
from panic_server.api.permissions import IsGlobalAdmin, IsRealGlobalAdmin, ReadAuthenticatedWriteAdmin
from panic_server.api.validation import require
from panic_server.services import admin as admin_service
from panic_server.services.audit import record_audit
from panic_server.services.view_as import assert_not_view_as, exit_view_as, start_view_as
from panic_server.store.client import get_db
from panic_server.store.errors import VersionConflict
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

# ======================================================================== sites


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
@permission_classes([ReadAuthenticatedWriteAdmin])
def sites_view(request: Request) -> Response:
    db = get_db()
    if request.method == "GET":
        return Response(admin_service.list_sites(db))

    django_request = request._request
    assert_not_view_as(django_request.context)
    body = request.data
    require(body, "code", "name")
    site = admin_service.create_site(db, code=body["code"], name=body["name"], description=body.get("description", ""))
    record_audit(
        db,
        django_request,
        action="admin.site.create",
        target_type="site",
        target_id=site.id,
        summary=f"Created site {site.code}",
    )
    return Response({"id": site.id, "code": site.code, "name": site.name, "description": site.description}, status=201)


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH", "DELETE"])
@permission_classes([IsGlobalAdmin])
def site_detail_view(request: Request, site_id: str) -> Response:
    db = get_db()
    django_request = request._request
    assert_not_view_as(django_request.context)
    current = sites_repo.get_site(db, site_id)
    version = expected_version(request, current.version, required=False)

    if request.method == "DELETE":
        try:
            admin_service.delete_site(db, site_id, version)
        except VersionConflict:
            raise version_conflict(sites_repo.get_site(db, site_id).version) from None
        record_audit(
            db,
            django_request,
            action="admin.site.delete",
            target_type="site",
            target_id=site_id,
            summary=f"Deleted site {current.code}",
        )
        return Response(status=204)

    body = request.data
    try:
        site = admin_service.update_site(db, site_id, version, **body)
    except VersionConflict:
        raise version_conflict(sites_repo.get_site(db, site_id).version) from None
    record_audit(
        db,
        django_request,
        action="admin.site.update",
        target_type="site",
        target_id=site_id,
        summary=f"Updated site {site.code}",
    )
    return Response({"id": site.id, "code": site.code, "name": site.name, "description": site.description})


# ======================================================================== teams


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
@permission_classes([ReadAuthenticatedWriteAdmin])
def teams_view(request: Request) -> Response:
    db = get_db()
    if request.method == "GET":
        return Response(admin_service.list_teams(db))

    django_request = request._request
    assert_not_view_as(django_request.context)
    body = request.data
    require(body, "code", "name")
    team = admin_service.create_team(db, code=body["code"], name=body["name"], description=body.get("description", ""))
    record_audit(
        db,
        django_request,
        action="admin.team.create",
        target_type="team",
        target_id=team.id,
        summary=f"Created team {team.code}",
    )
    return Response({"id": team.id, "code": team.code, "name": team.name, "description": team.description}, status=201)


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH", "DELETE"])
@permission_classes([IsGlobalAdmin])
def team_detail_view(request: Request, team_id: str) -> Response:
    db = get_db()
    django_request = request._request
    assert_not_view_as(django_request.context)
    current = teams_repo.get_team(db, team_id)
    version = expected_version(request, current.version, required=False)

    if request.method == "DELETE":
        try:
            result = admin_service.delete_team(db, team_id, version)
        except VersionConflict:
            raise version_conflict(teams_repo.get_team(db, team_id).version) from None
        record_audit(
            db,
            django_request,
            action="admin.team.delete",
            target_type="team",
            target_id=team_id,
            summary=f"Deleted team {current.code}",
            details=result,
        )
        return Response(result)

    body = request.data
    try:
        team = admin_service.update_team(db, team_id, version, **body)
    except VersionConflict:
        raise version_conflict(teams_repo.get_team(db, team_id).version) from None
    record_audit(
        db,
        django_request,
        action="admin.team.update",
        target_type="team",
        target_id=team_id,
        summary=f"Updated team {team.code}",
    )
    return Response({"id": team.id, "code": team.code, "name": team.name, "description": team.description})


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([IsGlobalAdmin])
def team_members_view(request: Request, team_id: str) -> Response:
    page = int(request.query_params.get("page", 1) or 1)
    page_size = min(int(request.query_params.get("page_size", 50) or 50), 100)
    return Response(admin_service.get_team_members(get_db(), team_id, page=page, page_size=page_size))


# ======================================================================== zones


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
@permission_classes([ReadAuthenticatedWriteAdmin])
def zones_view(request: Request) -> Response:
    db = get_db()
    if request.method == "GET":
        return Response(admin_service.list_zones(db, request._request.context.effective_user))

    django_request = request._request
    assert_not_view_as(django_request.context)
    body = request.data
    require(body, "name")
    zone = admin_service.create_zone(
        db,
        name=body["name"],
        description=body.get("description", ""),
        priority=body.get("priority", 100),
        cidrs=body.get("cidrs"),
    )
    record_audit(
        db,
        django_request,
        action="admin.zone.create",
        target_type="zone",
        target_id=zone.id,
        summary=f"Created zone {zone.name}",
    )
    return Response(
        {
            "id": zone.id,
            "name": zone.name,
            "description": zone.description,
            "priority": zone.priority,
            "cidrs": list(zone.cidrs),
            "builtin": zone.builtin,
            "version": zone.version,
        },
        status=201,
    )


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH", "DELETE"])
@permission_classes([IsGlobalAdmin])
def zone_detail_view(request: Request, zone_id: str) -> Response:
    db = get_db()
    django_request = request._request
    assert_not_view_as(django_request.context)
    current = zones_repo.get_zone(db, zone_id)
    version = expected_version(request, current.version, required=False)

    if request.method == "DELETE":
        try:
            admin_service.delete_zone(db, zone_id, version)
        except VersionConflict:
            raise version_conflict(zones_repo.get_zone(db, zone_id).version) from None
        record_audit(
            db,
            django_request,
            action="admin.zone.delete",
            target_type="zone",
            target_id=zone_id,
            summary=f"Deleted zone {current.name}",
        )
        return Response(status=204)

    body = request.data
    try:
        zone = admin_service.update_zone(db, zone_id, version, **body)
    except VersionConflict:
        raise version_conflict(zones_repo.get_zone(db, zone_id).version) from None
    record_audit(
        db,
        django_request,
        action="admin.zone.update",
        target_type="zone",
        target_id=zone_id,
        summary=f"Updated zone {zone.name}",
    )
    return Response(
        {
            "id": zone.id,
            "name": zone.name,
            "description": zone.description,
            "priority": zone.priority,
            "cidrs": list(zone.cidrs),
            "builtin": zone.builtin,
            "version": zone.version,
        }
    )


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([IsGlobalAdmin])
def zone_test_ip_view(request: Request) -> Response:
    ip = request.data.get("ip", "")
    return Response(admin_service.test_ip(get_db(), ip))


# ======================================================================== users


@extend_schema(methods=["GET"], operation_id="users_list")
@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
@permission_classes([IsGlobalAdmin])
def users_view(request: Request) -> Response:
    db = get_db()
    if request.method == "GET":
        qp = request.query_params
        rows = admin_service.list_users(
            db,
            q=qp.get("q", ""),
            permission=qp.get("permission") or None,
            team_id=qp.get("team_id") or None,
            disabled=(qp.get("disabled").lower() == "true") if qp.get("disabled") is not None else None,
        )
        paginator = PageEnvelopePagination()
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(page if page is not None else rows)

    django_request = request._request
    assert_not_view_as(django_request.context)
    body = request.data
    require(body, "username")
    user = admin_service.create_user(
        db,
        username=body["username"],
        display_name=body.get("display_name"),
        permissions=body.get("permissions"),
        team_ids=body.get("team_ids"),
    )
    record_audit(
        db,
        django_request,
        action="admin.user.create",
        target_type="user_account",
        target_id=user.id,
        summary=f"Pre-provisioned user {user.username}",
    )
    return Response(admin_service.user_summary(user), status=201)


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH"])
@permission_classes([IsGlobalAdmin])
def user_detail_view(request: Request, user_id: str) -> Response:
    db = get_db()
    if request.method == "GET":
        return Response(admin_service.get_user_detail(db, user_id))

    django_request = request._request
    assert_not_view_as(django_request.context)
    current = users_repo.get_user(db, user_id)
    version = expected_version(request, current.version, required=False)
    try:
        updated = admin_service.update_user(db, user_id, version, **request.data)
    except VersionConflict:
        raise version_conflict(users_repo.get_user(db, user_id).version) from None
    record_audit(
        db,
        django_request,
        action="admin.user.update",
        target_type="user_account",
        target_id=user_id,
        summary=f"Updated user {updated.username}",
        details={"fields": sorted(request.data.keys())},
    )
    return Response(admin_service.user_summary(updated))


# ======================================================================== orphans


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([IsGlobalAdmin])
def orphans_view(request: Request) -> Response:
    qp = request.query_params
    page = int(qp.get("page", 1) or 1)
    page_size = min(int(qp.get("page_size", 50) or 50), 100)
    return Response(
        admin_service.list_orphans(
            get_db(), kind=qp.get("kind") or None, q=qp.get("q", ""), page=page, page_size=page_size
        )
    )


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([IsGlobalAdmin])
def orphan_assign_view(request: Request, kind: str, item_id: str) -> Response:
    db = get_db()
    django_request = request._request
    assert_not_view_as(django_request.context)
    real = django_request.context.real_user
    assert real is not None
    username = request.data.get("username", "")
    result = admin_service.assign_orphan(db, real, kind, item_id, username)
    record_audit(
        db,
        django_request,
        action="admin.orphan.assign",
        target_type=kind,
        target_id=item_id,
        summary=f"Assigned orphaned {kind} {item_id} to {username}",
        details=result,
    )
    return Response(result)


# ======================================================================== View As


@extend_schema(
    tags=["admin"],
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiResponse(description="Bootstrap payload for the new perspective.")},
)
@api_view(["PUT", "DELETE"])
@permission_classes([IsRealGlobalAdmin])
def view_as_view(request: Request) -> Response:
    db = get_db()
    django_request = request._request
    if request.method == "PUT":
        target_user_id = request.data.get("user_id", "")
        body = start_view_as(db, django_request, target_user_id)
        return Response(body)
    # DELETE: the one mutation explicitly allowed while View As is active (API.md §4.7) -- never
    # calls assert_not_view_as.
    body = exit_view_as(db, django_request)
    return Response(body)


# ======================================================================== settings


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH"])
@permission_classes([ReadAuthenticatedWriteAdmin])
def settings_view(request: Request) -> Response:
    db = get_db()
    if request.method == "GET":
        return Response(admin_service.get_settings(db))

    django_request = request._request
    assert_not_view_as(django_request.context)
    real = django_request.context.real_user
    assert real is not None
    current_doc = settings_repo.get_system_settings(db)
    current_version = current_doc.version if current_doc is not None else 1
    version = expected_version(request, current_version, required=False)
    body: dict[str, Any] = request.data
    require(body, "default_global_dashboard_id")
    try:
        updated = admin_service.update_settings(db, real, version, body["default_global_dashboard_id"])
    except VersionConflict:
        refreshed = settings_repo.get_system_settings(db)
        raise version_conflict(refreshed.version if refreshed is not None else version) from None
    record_audit(
        db,
        django_request,
        action="admin.settings.update",
        target_type="system_settings",
        target_id="system",
        summary=f"Set the app-wide default dashboard to {updated.default_global_dashboard_id}",
    )
    return Response(admin_service.get_settings(db))


__all__ = [
    "orphan_assign_view",
    "orphans_view",
    "settings_view",
    "site_detail_view",
    "sites_view",
    "team_detail_view",
    "team_members_view",
    "teams_view",
    "user_detail_view",
    "users_view",
    "view_as_view",
    "zone_detail_view",
    "zone_test_ip_view",
    "zones_view",
]

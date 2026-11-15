"""``/api/v1/dashboards`` (API.md §4.3). ``PATCH``/``DELETE /dashboards/{id}`` and
``PUT .../layout`` **require** ``If-Match``.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_server.api.concurrency import expected_version, version_conflict
from panic_server.api.pagination import PageEnvelopePagination
from panic_server.api.permissions import IsAuthenticated
from panic_server.api.validation import require
from panic_server.services import dashboards as dashboards_service
from panic_server.services.audit import record_audit
from panic_server.services.view_as import assert_not_view_as
from panic_server.store.client import get_db
from panic_server.store.errors import VersionConflict
from panic_server.store.repos import dashboards as dashboards_repo


@extend_schema(methods=["GET"], operation_id="dashboards_list")
@extend_schema(tags=["dashboards"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def dashboards_view(request: Request) -> Response:
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    assert effective is not None
    db = get_db()

    if request.method == "GET":
        qp = request.query_params
        rows = dashboards_service.list_dashboard_summaries(
            db, effective, scope=qp.get("scope") or None, q=qp.get("q", "")
        )
        paginator = PageEnvelopePagination()
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(page if page is not None else rows)

    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    body = request.data
    require(body, "title")
    dashboard = dashboards_service.create_dashboard(
        db,
        real,
        title=body["title"],
        description=body.get("description", ""),
        scope=body.get("scope", "GLOBAL"),
        team_ids=body.get("team_ids"),
        owner_usernames=body.get("owner_usernames"),
        always_display=bool(body.get("always_display", False)),
        icon=body.get("icon") or "dashboard",
        set_as_user_default=bool(body.get("set_as_user_default", False)),
        set_as_global_default=bool(body.get("set_as_global_default", False)),
    )
    record_audit(
        db,
        django_request,
        action="dashboard.create",
        target_type="dashboard",
        target_id=dashboard.id,
        summary=f"{real.username} created dashboard {dashboard.title}",
    )
    return Response(dashboards_service.get_dashboard_detail(db, effective, dashboard.id), status=201)


@extend_schema(tags=["dashboards"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def dashboard_detail_view(request: Request, dashboard_id: str) -> Response:
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    assert effective is not None
    db = get_db()

    if request.method == "GET":
        return Response(dashboards_service.get_dashboard_detail(db, effective, dashboard_id))

    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    current = dashboards_repo.get_dashboard(db, dashboard_id)
    version = expected_version(request, current.version, required=True)

    if request.method == "DELETE":
        try:
            dashboards_service.delete_dashboard(db, real, dashboard_id, version)
        except VersionConflict:
            raise version_conflict(dashboards_repo.get_dashboard(db, dashboard_id).version) from None
        record_audit(
            db,
            django_request,
            action="dashboard.delete",
            target_type="dashboard",
            target_id=dashboard_id,
            summary=f"{real.username} deleted dashboard {current.title}",
        )
        return Response(status=204)

    body = request.data
    try:
        dashboard = dashboards_service.update_dashboard_properties(db, real, dashboard_id, version, **body)
    except VersionConflict:
        raise version_conflict(dashboards_repo.get_dashboard(db, dashboard_id).version) from None
    record_audit(
        db,
        django_request,
        action="dashboard.update",
        target_type="dashboard",
        target_id=dashboard_id,
        summary=f"{real.username} updated dashboard {dashboard.title}",
    )
    return Response(dashboards_service.get_dashboard_detail(db, effective, dashboard.id))


@extend_schema(tags=["dashboards"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def dashboard_layout_view(request: Request, dashboard_id: str) -> Response:
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    assert effective is not None
    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    db = get_db()
    current = dashboards_repo.get_dashboard(db, dashboard_id)
    version = expected_version(request, current.version, required=True)
    widgets = request.data.get("widgets", [])
    try:
        dashboard = dashboards_service.replace_layout(db, real, dashboard_id, version, widgets)
    except VersionConflict:
        raise version_conflict(dashboards_repo.get_dashboard(db, dashboard_id).version) from None
    record_audit(
        db,
        django_request,
        action="dashboard.layout.update",
        target_type="dashboard",
        target_id=dashboard_id,
        summary=f"{real.username} updated the layout of {dashboard.title}",
    )
    return Response(dashboards_service.get_dashboard_detail(db, effective, dashboard.id))


__all__ = ["dashboard_detail_view", "dashboard_layout_view", "dashboards_view"]

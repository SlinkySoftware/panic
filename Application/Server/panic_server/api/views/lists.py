"""``/api/v1/lists`` (API.md §4.6). ``PUT``/``DELETE /lists/{id}`` **require** ``If-Match``."""

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
from panic_server.services import lists as lists_service
from panic_server.services.audit import record_audit
from panic_server.services.view_as import assert_not_view_as
from panic_server.store.client import get_db
from panic_server.store.errors import VersionConflict
from panic_server.store.repos import lists as lists_repo


@extend_schema(methods=["GET"], operation_id="lists_list")
@extend_schema(tags=["lists"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def lists_view(request: Request) -> Response:
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    assert effective is not None
    db = get_db()

    if request.method == "GET":
        qp = request.query_params
        rows = lists_service.list_lists(
            db, effective, group=qp.get("group") or None, q=qp.get("q", ""), sort=qp.get("sort", "title")
        )
        paginator = PageEnvelopePagination()
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(page if page is not None else rows)

    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    body = request.data
    require(body, "title")
    lst = lists_service.create_list(
        db,
        real,
        title=body["title"],
        description=body.get("description", ""),
        scope=body.get("scope", "GLOBAL"),
        team_ids=body.get("team_ids"),
        owner_usernames=body.get("owner_usernames"),
        item_ids=body.get("item_ids"),
    )
    record_audit(
        db,
        django_request,
        action="list.create",
        target_type="endpoint_list",
        target_id=lst.id,
        summary=f"{real.username} created list {lst.title}",
    )
    return Response(lists_service.get_list_detail(db, context, lst.id), status=201)


@extend_schema(tags=["lists"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def list_detail_view(request: Request, list_id: str) -> Response:
    django_request = request._request
    context = django_request.context
    assert context.effective_user is not None
    db = get_db()

    if request.method == "GET":
        return Response(lists_service.get_list_detail(db, context, list_id))

    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    current = lists_repo.get_list(db, list_id)
    version = expected_version(request, current.version, required=True)

    if request.method == "DELETE":
        try:
            lists_service.delete_list(db, real, list_id, version)
        except VersionConflict:
            raise version_conflict(lists_repo.get_list(db, list_id).version) from None
        record_audit(
            db,
            django_request,
            action="list.delete",
            target_type="endpoint_list",
            target_id=list_id,
            summary=f"{real.username} deleted list {current.title}",
        )
        return Response(status=204)

    body = request.data
    require(body, "title")
    try:
        lst = lists_service.replace_list(
            db,
            real,
            list_id,
            version,
            title=body["title"],
            description=body.get("description", ""),
            scope=body.get("scope", str(current.scope)),
            team_ids=body.get("team_ids"),
            owner_usernames=body.get("owner_usernames"),
            item_ids=body.get("item_ids", []),
        )
    except VersionConflict:
        raise version_conflict(lists_repo.get_list(db, list_id).version) from None
    record_audit(
        db,
        django_request,
        action="list.update",
        target_type="endpoint_list",
        target_id=list_id,
        summary=f"{real.username} updated list {lst.title}",
    )
    return Response(lists_service.get_list_detail(db, context, lst.id))


__all__ = ["list_detail_view", "lists_view"]

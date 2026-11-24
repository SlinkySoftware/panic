"""``/api/v1/catalog`` (API.md §4.5)."""

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
from panic_server.services import catalog as catalog_service
from panic_server.services.audit import record_audit
from panic_server.services.view_as import assert_not_view_as
from panic_server.store.client import get_db
from panic_server.store.errors import VersionConflict
from panic_server.store.repos import catalog as catalog_repo


@extend_schema(methods=["GET"], operation_id="catalog_list")
@extend_schema(tags=["catalog"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def catalog_view(request: Request) -> Response:
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    assert effective is not None
    db = get_db()

    if request.method == "GET":
        qp = request.query_params
        rows = catalog_service.list_catalog(
            db,
            effective,
            context.zone,
            group=qp.get("group") or None,
            protocol=qp.get("protocol") or None,
            site=qp.get("site") or None,
            zone_id=qp.get("zone_id") or None,
            team_id=qp.get("team_id") or None,
            q=qp.get("q", ""),
            sort=qp.get("sort", "title"),
        )
        paginator = PageEnvelopePagination()
        page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response(page if page is not None else rows)

    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    body = request.data
    require(body, "title", "host")
    item = catalog_service.create_catalog_item(
        db,
        real,
        title=body["title"],
        host=body["host"],
        connections=catalog_service.parse_connections(body.get("connections")),
        site=body.get("site", "2SYA"),
        account_override=body.get("account_override", ""),
        description=body.get("description", ""),
        tags=body.get("tags"),
        scope=body.get("scope", "GLOBAL"),
        team_ids=body.get("team_ids"),
        owner_usernames=body.get("owner_usernames"),
        zone_ids=body.get("zone_ids"),
        force_allow_duplicate=bool(body.get("force_allow_duplicate", False)),
    )
    record_audit(
        db,
        django_request,
        action="catalog.create",
        target_type="catalog_item",
        target_id=item.id,
        summary=f"{real.username} created catalog item {item.title}",
    )
    return Response(catalog_service.get_catalog_item_detail(db, effective, item.id), status=201)


@extend_schema(tags=["catalog"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def catalog_detail_view(request: Request, item_id: str) -> Response:
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    assert effective is not None
    db = get_db()

    if request.method == "GET":
        return Response(catalog_service.get_catalog_item_detail(db, effective, item_id))

    assert_not_view_as(context)
    real = context.real_user
    assert real is not None
    current = catalog_repo.get_catalog_item(db, item_id)
    version = expected_version(request, current.version, required=False)

    if request.method == "DELETE":
        try:
            catalog_service.delete_catalog_item(db, real, item_id, version)
        except VersionConflict:
            raise version_conflict(catalog_repo.get_catalog_item(db, item_id).version) from None
        record_audit(
            db,
            django_request,
            action="catalog.delete",
            target_type="catalog_item",
            target_id=item_id,
            summary=f"{real.username} deleted catalog item {current.title}",
        )
        return Response(status=204)

    body = request.data
    fields = {k: v for k, v in body.items() if k != "force_allow_duplicate"}
    try:
        item = catalog_service.update_catalog_item(
            db, real, item_id, version, force_allow_duplicate=bool(body.get("force_allow_duplicate", False)), **fields
        )
    except VersionConflict:
        raise version_conflict(catalog_repo.get_catalog_item(db, item_id).version) from None
    record_audit(
        db,
        django_request,
        action="catalog.update",
        target_type="catalog_item",
        target_id=item_id,
        summary=f"{real.username} updated catalog item {item.title}",
    )
    return Response(catalog_service.get_catalog_item_detail(db, effective, item.id))


@extend_schema(tags=["catalog"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def catalog_preview_view(request: Request) -> Response:
    django_request = request._request
    effective = django_request.context.effective_user
    assert effective is not None
    body = request.data
    require(body, "host")
    result = catalog_service.preview_catalog_item(
        get_db(),
        effective,
        host=body["host"],
        connections=catalog_service.parse_connections(body.get("connections")),
        account_override=body.get("account_override", ""),
        scope=body.get("scope", "GLOBAL"),
        exclude_id=body.get("item_id") or "",
    )
    return Response(result)


__all__ = ["catalog_detail_view", "catalog_preview_view", "catalog_view"]

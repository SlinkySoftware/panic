"""``/api/v1/ui/...`` -- bootstrap, dashboard detail, search (API.md §4.2)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_server.api.etag import etag_response
from panic_server.api.permissions import IsAuthenticated
from panic_server.api.serializers import (
    BootstrapResponseSerializer,
    DashboardViewResponseSerializer,
    SearchResponseSerializer,
)
from panic_server.services.bootstrap import build_bootstrap
from panic_server.services.dashboards_read import build_dashboard_view
from panic_server.services.search import DEFAULT_LIMIT, MAX_LIMIT, run_search
from panic_server.store.client import get_db


@extend_schema(tags=["ui"], responses=BootstrapResponseSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bootstrap_view(request: Request) -> Response:
    """``GET /api/v1/ui/bootstrap``: instance/me/view_as/permissions/client/nav/default dashboard."""
    body = build_bootstrap(get_db(), request._request.context)
    return Response(body)


@extend_schema(tags=["ui"], responses=DashboardViewResponseSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_view(request: Request, dashboard_id: str) -> Response:
    """``GET /api/v1/ui/dashboards/{id}``: visible dashboards only; weak ``ETag``/``If-None-Match``."""
    django_request = request._request
    body = build_dashboard_view(get_db(), django_request.context, dashboard_id)
    return etag_response(django_request, body)


@extend_schema(
    tags=["ui"],
    parameters=[
        OpenApiParameter("q", str, description="Whitespace-split prefix-match query (<2 chars -> no results)."),
        OpenApiParameter("limit", int, description=f"Max results, 1..{MAX_LIMIT} (default {DEFAULT_LIMIT})."),
    ],
    responses=SearchResponseSerializer,
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_view(request: Request) -> Response:
    """``GET /api/v1/ui/search?q=&limit=``: dashboards, items and lists, ranked and capped."""
    q = request.query_params.get("q", "")
    try:
        limit = int(request.query_params.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    body = run_search(get_db(), request._request.context, q, limit)
    return Response(body)


__all__ = ["bootstrap_view", "dashboard_view", "search_view"]

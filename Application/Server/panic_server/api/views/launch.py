"""``GET /api/v1/launch/rdp/{id}.rdp`` -- the ``.rdp`` download endpoint (API.md §4.2/§4.3, F3)."""

from __future__ import annotations

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request

from panic_server.api.permissions import IsAuthenticated
from panic_server.services.launch import get_rdp_download
from panic_server.store.client import get_db


@extend_schema(
    tags=["launch"],
    parameters=[OpenApiParameter("user", str, description="Override the embedded remote username.")],
    responses={200: OpenApiTypes.BINARY},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def rdp_download_view(request: Request, item_id: str) -> HttpResponse:
    """Visible, RDP-protocol item; ``404`` when invisible or (policy ``HIDE``) unreachable."""
    django_request = request._request
    context = django_request.context
    effective = context.effective_user
    override_user = request.query_params.get("user") or None

    content, filename = get_rdp_download(
        get_db(),
        item_id=item_id,
        caller=effective,
        active_zone=context.zone,
        override_user=override_user,
        client_ip=context.client_ip,
        actor_username=(context.real_user.username if context.real_user else effective.username),
        view_as_username=(effective.username if context.view_as_active else None),
        request_id=getattr(django_request, "request_id", None),
    )
    response = HttpResponse(content, content_type="application/x-rdp")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


__all__ = ["rdp_download_view"]

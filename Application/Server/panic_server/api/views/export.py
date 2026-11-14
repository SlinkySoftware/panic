"""``GET /api/v1/export?shared_only=`` -- portable JSON export (API.md §4.7). A thin, audited
wrapper around ``panic_server.services.portability.export_state`` (T-S6-03); the export format
itself is owned by that task and is not reimplemented here.
"""

from __future__ import annotations

import json

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request

from panic_server.api.permissions import IsGlobalAdmin
from panic_server.services.audit import record_audit
from panic_server.services.portability import export_state
from panic_server.store.client import get_db


@extend_schema(
    tags=["admin"],
    parameters=[OpenApiParameter("shared_only", bool, required=False)],
    responses={200: OpenApiTypes.BINARY},
)
@api_view(["GET"])
@permission_classes([IsGlobalAdmin])
def export_view(request: Request) -> HttpResponse:
    django_request = request._request
    shared_only = request.query_params.get("shared_only", "").strip().lower() in {"1", "true", "yes"}
    db = get_db()
    doc = export_state(db, shared_only=shared_only)

    real = django_request.context.real_user
    record_audit(
        db,
        django_request,
        action="admin.export",
        target_type="system",
        target_id="export",
        summary=f"{real.username if real is not None else 'unknown'} exported state (shared_only={shared_only})",
        details={"shared_only": shared_only},
    )

    body = json.dumps(doc, indent=2).encode("utf-8")
    response = HttpResponse(body, content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="panic-export.json"'
    response["Cache-Control"] = "no-store"
    return response


__all__ = ["export_view"]

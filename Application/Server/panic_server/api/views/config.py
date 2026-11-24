"""Config export and merge-import (super admin), under ``/api/v1/admin/config/`` (API.md §4.7).
Thin, audited wrappers around ``panic_server.services.config_transfer``, which owns the format.

The full backup (users, dashboards, settings too) stays the ``panic_export`` / ``panic_import``
management commands.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_common.errors import ErrorCode
from panic_server.api.errors import ApiError
from panic_server.api.permissions import IsRealSuperAdmin
from panic_server.services import config_transfer
from panic_server.services.audit import record_audit
from panic_server.services.view_as import assert_not_view_as
from panic_server.store.client import get_db


def _actor(request: Request) -> str:
    real = request._request.context.real_user
    assert real is not None  # IsRealSuperAdmin guarantees this
    return str(real.username)


@extend_schema(tags=["admin"], responses={200: OpenApiTypes.BINARY})
@api_view(["GET"])
@permission_classes([IsRealSuperAdmin])
def config_export_view(request: Request) -> HttpResponse:
    db = get_db()
    doc = config_transfer.export_config(db)
    counts = {s: len(doc[s]) for s in config_transfer.SECTIONS}
    record_audit(
        db,
        request._request,
        action="admin.config.export",
        target_type="system",
        target_id="config",
        summary=f"{_actor(request)} exported config ({', '.join(f'{n} {s}' for s, n in counts.items())})",
        details=counts,
    )
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(json.dumps(doc, indent=2).encode("utf-8"), content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="panic-config-{stamp}.json"'
    response["Cache-Control"] = "no-store"
    return response


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([IsRealSuperAdmin])
def config_import_preview_view(request: Request) -> Response:
    """Body: the export document. Writes nothing."""
    plan = config_transfer.plan_import(get_db(), request.data, _actor(request))
    return Response(plan.preview())


@extend_schema(tags=["admin"], request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([IsRealSuperAdmin])
def config_import_view(request: Request) -> Response:
    """Body: ``{document, plan_digest}`` (the digest from the preview the user confirmed)."""
    django_request = request._request
    assert_not_view_as(django_request.context)
    body = request.data
    if not isinstance(body, dict) or "document" not in body:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "Send {document, plan_digest}.", status_code=400)
    db = get_db()
    plan = config_transfer.apply_import(db, body["document"], str(body.get("plan_digest") or ""), _actor(request))
    summary = plan.summary()
    record_audit(
        db,
        django_request,
        action="admin.config.import",
        target_type="system",
        target_id="config",
        summary=f"{_actor(request)} imported config: "
        + ", ".join(f"{s} +{c['added']} ~{c['changed']}" for s, c in summary.items()),
        details={
            "summary": summary,
            "changes": [c for c in plan.preview()["changes"] if c["action"] != "CONFLICT"],
            "conflicts": [c for c in plan.preview()["changes"] if c["action"] == "CONFLICT"],
        },
    )
    return Response({"summary": summary, "warnings": plan.warnings})


__all__ = ["config_export_view", "config_import_preview_view", "config_import_view"]

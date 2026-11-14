"""``GET /api/v1/audit`` -- keyset-paged audit trail (API.md §4.7, closes F2)."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_common.models import AuditLogEntry
from panic_server.api.pagination import encode_cursor, keyset_params
from panic_server.api.permissions import IsGlobalAdmin
from panic_server.store.client import get_db
from panic_server.store.repos import audit as audit_repo

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _entry_dict(e: AuditLogEntry) -> dict[str, object]:
    return {
        "id": e.id,
        "created_at": e.created_at,
        "actor_username": e.actor_username,
        "view_as_username": e.view_as_username,
        "action": e.action,
        "target_type": e.target_type,
        "target_id": e.target_id,
        "summary": e.summary,
        "details": e.details,
        "client_ip": e.client_ip,
        "zone_id": e.zone_id,
        "request_id": e.request_id,
    }


@extend_schema(
    tags=["audit"],
    responses=OpenApiTypes.OBJECT,
    parameters=[
        OpenApiParameter("actor", str, required=False),
        OpenApiParameter("action", str, required=False),
        OpenApiParameter("target_type", str, required=False),
        OpenApiParameter("target_id", str, required=False),
        OpenApiParameter("q", str, required=False, description="Substring match against each entry's summary."),
        OpenApiParameter("since", str, required=False, description="RFC 3339; inclusive lower bound on created_at."),
        OpenApiParameter("until", str, required=False, description="RFC 3339; inclusive upper bound on created_at."),
        OpenApiParameter("limit", int, required=False, description=f"<= {MAX_LIMIT} (default {DEFAULT_LIMIT})."),
        OpenApiParameter("cursor", str, required=False),
    ],
)
@api_view(["GET"])
@permission_classes([IsGlobalAdmin])
def audit_view(request: Request) -> Response:
    """``GET /api/v1/audit?actor=&action=&target_type=&target_id=&q=&since=&until=&limit=&cursor=``.

    Admin-only (F2). ``actor``/``action``/``target_type``+``target_id`` are proper indexed
    filters on ``store.repos.audit.list_audit``; ``q``/``since``/``until`` are applied to the
    already keyset-paged page in Python -- this is an admin diagnostics screen, not a
    payload-budgeted UI read, so a slightly coarser filter pass here is an acceptable trade
    against adding three more indexed query shapes to an append-only, TTL-bounded collection.
    """
    limit, cursor = keyset_params(request, default_limit=DEFAULT_LIMIT, max_limit=MAX_LIMIT)
    before = (cursor["created_at"], cursor["id"]) if cursor and "created_at" in cursor and "id" in cursor else None

    db = get_db()
    entries = audit_repo.list_audit(
        db,
        limit=limit,
        actor_username=request.query_params.get("actor") or None,
        action=request.query_params.get("action") or None,
        target_type=request.query_params.get("target_type") or None,
        target_id=request.query_params.get("target_id") or None,
        before=before,
    )

    q = request.query_params.get("q")
    if q:
        needle = q.strip().lower()
        entries = [e for e in entries if needle in e.summary.lower()]
    since = request.query_params.get("since")
    if since:
        entries = [e for e in entries if e.created_at >= since]
    until = request.query_params.get("until")
    if until:
        entries = [e for e in entries if e.created_at <= until]

    next_cursor = None
    if entries and len(entries) == limit:
        last = entries[-1]
        next_cursor = encode_cursor({"created_at": last.created_at, "id": last.id})
    return Response({"results": [_entry_dict(e) for e in entries], "next_cursor": next_cursor})


__all__ = ["audit_view"]

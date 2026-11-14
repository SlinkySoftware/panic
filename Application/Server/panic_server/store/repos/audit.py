"""``audit_log`` repository (DATA_MODEL.md §4.9). Append-only; paged by keyset, newest first."""

from __future__ import annotations

import datetime as dt
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from panic_common.models import AuditLogEntry
from panic_server.store.cas import base_kwargs, utcnow

COLLECTION = "audit_log"


def _to_model(doc: dict[str, Any]) -> AuditLogEntry:
    return AuditLogEntry(**base_kwargs(doc))


def append_audit(
    db: Database[dict[str, Any]],
    *,
    actor_username: str,
    action: str,
    target_type: str,
    target_id: str,
    summary: str,
    client_ip: str,
    details: dict[str, Any] | None = None,
    view_as_username: str | None = None,
    zone_id: str | None = None,
    request_id: str | None = None,
) -> AuditLogEntry:
    doc: dict[str, Any] = {
        "created_at": utcnow(),
        "actor_username": actor_username,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "summary": summary,
        "details": details or {},
        "client_ip": client_ip,
    }
    if view_as_username is not None:
        doc["view_as_username"] = view_as_username
    if zone_id is not None:
        doc["zone_id"] = zone_id
    if request_id is not None:
        doc["request_id"] = request_id
    result = db[COLLECTION].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _to_model(doc)


def list_audit(
    db: Database[dict[str, Any]],
    *,
    limit: int = 50,
    actor_username: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    before: tuple[str, str] | None = None,
) -> list[AuditLogEntry]:
    """Newest first, keyset-paged. ``before`` is ``(created_at_rfc3339, id)`` of the last row seen."""
    query: dict[str, Any] = {}
    if actor_username is not None:
        query["actor_username"] = actor_username
    if action is not None:
        query["action"] = action
    if target_type is not None:
        query["target_type"] = target_type
        if target_id is not None:
            query["target_id"] = target_id
    if before is not None:
        before_created_at, before_id = before
        before_dt = dt.datetime.fromisoformat(before_created_at.replace("Z", "+00:00"))
        before_oid = ObjectId(before_id)
        query["$or"] = [
            {"created_at": {"$lt": before_dt}},
            {"created_at": before_dt, "_id": {"$lt": before_oid}},
        ]
    cursor = db[COLLECTION].find(query).sort([("created_at", -1), ("_id", -1)]).limit(limit)
    return [_to_model(d) for d in cursor]

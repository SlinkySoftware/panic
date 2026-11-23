"""``zones`` (Security Zones) repository (DATA_MODEL.md §4.4).

Zones are few and every zoned request needs all of them, so the full set is cached per
process for ``PANIC_ZONE_CACHE_TTL_S`` (default 10s) and the cache is invalidated on writes
from *this* process (other processes simply wait out the TTL -- acceptable staleness for a
rarely-changed, operator-facing resource).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from django.conf import settings
from pymongo.database import Database

from panic_common.models import SecurityZone
from panic_server.store.cas import (
    base_kwargs,
    cas_update,
    delete_versioned,
    from_iso_z,
    get_or_404,
    insert_versioned,
    new_id,
    utcnow,
)
from panic_server.store.errors import DuplicateKey, NotFound

COLLECTION = "zones"
DEFAULT_ZONE_ID = "zone-default"
DEFAULT_ZONE_NAME = "Default"

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_ttl_s() -> float:
    return float(settings.PANIC_ZONE_CACHE_TTL_S)


def _to_model(doc: dict[str, Any]) -> SecurityZone:
    return SecurityZone(**base_kwargs(doc))


def invalidate_cache(db: Database[dict[str, Any]]) -> None:
    with _cache_lock:
        _cache.pop(str(db.name), None)


def list_zones(db: Database[dict[str, Any]]) -> list[SecurityZone]:
    """All zones, sorted by priority desc then name, cached for ``PANIC_ZONE_CACHE_TTL_S``."""
    now = time.monotonic()
    key = str(db.name)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and (now - cached[0]) < _cache_ttl_s():
            docs = cached[1]
        else:
            docs = list(db[COLLECTION].find().sort([("priority", -1), ("name", 1)]))
            _cache[key] = (now, docs)
    return [_to_model(d) for d in docs]


def get_zone(db: Database[dict[str, Any]], zone_id: str) -> SecurityZone:
    return _to_model(get_or_404(db[COLLECTION], zone_id))


def get_zone_by_name(db: Database[dict[str, Any]], name: str) -> SecurityZone | None:
    doc = db[COLLECTION].find_one({"name": name})
    return _to_model(doc) if doc else None


def create_zone(
    db: Database[dict[str, Any]],
    *,
    name: str,
    description: str = "",
    priority: int = 100,
    cidrs: list[str] | None = None,
) -> SecurityZone:
    now = utcnow()
    doc = {
        "_id": new_id(),
        "name": name,
        "description": description,
        "priority": priority,
        "cidrs": cidrs or [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    model = _to_model(insert_versioned(db[COLLECTION], doc))
    invalidate_cache(db)
    return model


def ensure_default_zone(db: Database[dict[str, Any]]) -> SecurityZone:
    """Idempotently create the built-in Default zone (``panic_migrate`` step 1)."""
    existing = db[COLLECTION].find_one({"_id": DEFAULT_ZONE_ID})
    if existing is not None:
        return _to_model(existing)
    now = utcnow()
    doc = {
        "_id": DEFAULT_ZONE_ID,
        "name": DEFAULT_ZONE_NAME,
        "description": "The built-in catch-all zone for unclassified client locations.",
        "priority": 0,
        "cidrs": [],
        "builtin": True,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    try:
        model = _to_model(insert_versioned(db[COLLECTION], doc))
    except DuplicateKey:
        # Lost a race with another process; the Default zone now exists either way.
        model = _to_model(get_or_404(db[COLLECTION], DEFAULT_ZONE_ID))
    invalidate_cache(db)
    return model


def update_zone(
    db: Database[dict[str, Any]],
    zone_id: str,
    expected_version: int,
    *,
    name: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    cidrs: list[str] | None = None,
) -> SecurityZone:
    existing = get_or_404(db[COLLECTION], zone_id)
    if existing.get("builtin") and (name is not None or cidrs is not None):
        raise ValueError("the built-in Default zone cannot be renamed or given CIDRs")
    fields: dict[str, Any] = {"updated_at": utcnow()}
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description
    if priority is not None:
        fields["priority"] = priority
    if cidrs is not None:
        fields["cidrs"] = cidrs
    doc = cas_update(db[COLLECTION], zone_id, expected_version, {"$set": fields, "$inc": {"version": 1}})
    model = _to_model(doc)
    invalidate_cache(db)
    return model


def delete_zone(db: Database[dict[str, Any]], zone_id: str, expected_version: int) -> None:
    if zone_id == DEFAULT_ZONE_ID:
        raise ValueError("the built-in Default zone cannot be deleted")
    delete_versioned(db[COLLECTION], zone_id, expected_version)
    invalidate_cache(db)
    db["catalog_items"].update_many({"zone_ids": zone_id}, {"$pull": {"zone_ids": zone_id}})


def upsert_zone(db: Database[dict[str, Any]], model: SecurityZone) -> SecurityZone:
    """Insert-or-fully-replace a zone by ``model.id``, including the builtin Default zone."""
    doc = {
        "name": model.name,
        "description": model.description,
        "priority": model.priority,
        "cidrs": model.cidrs,
        "builtin": model.builtin,
        "created_at": from_iso_z(model.created_at),
        "updated_at": from_iso_z(model.updated_at),
        "version": model.version,
    }
    db[COLLECTION].update_one({"_id": model.id}, {"$set": doc}, upsert=True)
    invalidate_cache(db)
    return model


def delete_all_zones(db: Database[dict[str, Any]]) -> int:
    """Wipe every zone, including the builtin Default zone (``panic_seed --reset``).

    Callers must re-create the Default zone afterwards (``ensure_default_zone``).
    """
    count = db[COLLECTION].delete_many({}).deleted_count
    invalidate_cache(db)
    return count


__all__ = [
    "DEFAULT_ZONE_ID",
    "DEFAULT_ZONE_NAME",
    "NotFound",
    "create_zone",
    "delete_all_zones",
    "delete_zone",
    "ensure_default_zone",
    "get_zone",
    "get_zone_by_name",
    "invalidate_cache",
    "list_zones",
    "update_zone",
    "upsert_zone",
]

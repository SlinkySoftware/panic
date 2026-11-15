"""``system_settings`` repository (DATA_MODEL.md §4.8): a single fixed-id document."""

from __future__ import annotations

import threading
import time
from typing import Any

from django.conf import settings as django_settings
from pymongo.database import Database

from panic_common.models import SystemSettings
from panic_server.store.cas import base_kwargs, cas_update, from_iso_z, insert_versioned, utcnow
from panic_server.store.errors import DuplicateKey

COLLECTION = "system_settings"
DOC_ID = "system"


def _to_model(doc: dict[str, Any]) -> SystemSettings:
    kwargs = base_kwargs(doc)
    kwargs.pop("id", None)
    return SystemSettings(**kwargs)


def get_system_settings(db: Database[dict[str, Any]]) -> SystemSettings | None:
    doc = db[COLLECTION].find_one({"_id": DOC_ID})
    return _to_model(doc) if doc else None


def ensure_system_settings(
    db: Database[dict[str, Any]], *, default_global_dashboard_id: str, updated_by: str
) -> SystemSettings:
    """Idempotently create the settings document (``panic_migrate`` step 1)."""
    existing = db[COLLECTION].find_one({"_id": DOC_ID})
    if existing is not None:
        return _to_model(existing)
    now = utcnow()
    doc = {
        "_id": DOC_ID,
        "default_global_dashboard_id": default_global_dashboard_id,
        "updated_by": updated_by,
        "updated_at": now,
        "version": 1,
    }
    try:
        return _to_model(insert_versioned(db[COLLECTION], doc))
    except DuplicateKey:
        return _to_model(db[COLLECTION].find_one({"_id": DOC_ID}))  # type: ignore[arg-type]


def set_default_global_dashboard(
    db: Database[dict[str, Any]],
    expected_version: int,
    *,
    default_global_dashboard_id: str,
    updated_by: str,
) -> SystemSettings:
    doc = cas_update(
        db[COLLECTION],
        DOC_ID,
        expected_version,
        {
            "$set": {
                "default_global_dashboard_id": default_global_dashboard_id,
                "updated_by": updated_by,
                "updated_at": utcnow(),
            },
            "$inc": {"version": 1},
        },
    )
    return _to_model(doc)


def upsert_system_settings(db: Database[dict[str, Any]], model: SystemSettings) -> SystemSettings:
    """Insert-or-fully-replace the single settings document (T-S6-03: portable import)."""
    doc = {
        "default_global_dashboard_id": model.default_global_dashboard_id,
        "ssh_uri_enabled": model.ssh_uri_enabled,
        "ssh_uri_scheme": model.ssh_uri_scheme,
        "updated_by": model.updated_by,
        "updated_at": from_iso_z(model.updated_at),
        "version": model.version,
    }
    db[COLLECTION].update_one({"_id": DOC_ID}, {"$set": doc}, upsert=True)
    return model


def set_ssh_uri(
    db: Database[dict[str, Any]], expected_version: int, *, enabled: bool, scheme: str, updated_by: str
) -> SystemSettings:
    doc = cas_update(
        db[COLLECTION],
        DOC_ID,
        expected_version,
        {
            "$set": {
                "ssh_uri_enabled": enabled,
                "ssh_uri_scheme": scheme,
                "updated_by": updated_by,
                "updated_at": utcnow(),
            },
            "$inc": {"version": 1},
        },
    )
    invalidate_ssh_uri_cache()
    return _to_model(doc)


# SSH URI config is read for every SSH item view: cache it per process (same TTL as the zone cache).
_ssh_cache_lock = threading.Lock()
_ssh_cache: tuple[float, str | None] | None = None


def invalidate_ssh_uri_cache() -> None:
    global _ssh_cache
    with _ssh_cache_lock:
        _ssh_cache = None


def ssh_uri_scheme(db: Database[dict[str, Any]]) -> str | None:
    """The SSH handler scheme when enabled, else ``None`` (cached for ``PANIC_ZONE_CACHE_TTL_S``)."""
    global _ssh_cache
    now = time.monotonic()
    with _ssh_cache_lock:
        if _ssh_cache is not None and now - _ssh_cache[0] < float(django_settings.PANIC_ZONE_CACHE_TTL_S):
            return _ssh_cache[1]
    doc = get_system_settings(db)
    defaults = SystemSettings(default_global_dashboard_id="")
    enabled = doc.ssh_uri_enabled if doc else defaults.ssh_uri_enabled
    scheme = (doc.ssh_uri_scheme if doc else defaults.ssh_uri_scheme) if enabled else None
    with _ssh_cache_lock:
        _ssh_cache = (now, scheme)
    return scheme


def delete_system_settings(db: Database[dict[str, Any]]) -> int:
    """Wipe the settings document (``panic_seed --reset``). Returns the number deleted (0 or 1)."""
    return db[COLLECTION].delete_many({}).deleted_count

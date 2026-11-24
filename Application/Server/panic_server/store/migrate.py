"""Idempotent data migrations against the PANIC database (DATA_MODEL.md §4.13).

Run by ``manage.py panic_migrate`` (a thin wrapper -- this module is where the pymongo-touching
logic lives, per AR-4.1). ``schema_meta`` (``_id: "schema"``) records the highest applied step
number, so new steps 2, 3, ... can be appended to :data:`STEPS` without rewriting this runner,
and a re-run only applies what's missing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pymongo.database import Database

from panic_common.models import CatalogItem
from panic_server.store.cas import base_kwargs, utcnow
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import zones as zones_repo

SCHEMA_COLLECTION = "schema_meta"
SCHEMA_DOC_ID = "schema"

MigrationFn = Callable[[Database[dict[str, Any]]], str]


def _step_1_default_zone_and_settings(db: Database[dict[str, Any]]) -> str:
    """Create the built-in Default zone and the ``system`` settings document (idempotent)."""
    zone = zones_repo.ensure_default_zone(db)
    settings_doc = settings_repo.ensure_system_settings(db, default_global_dashboard_id="", updated_by="system")
    return (
        f"ensured zone {zone.id!r} ({zone.name!r}) and system_settings "
        f"(default_global_dashboard_id={settings_doc.default_global_dashboard_id!r})"
    )


def _step_2_catalog_connections(db: Database[dict[str, Any]]) -> str:
    """Single-protocol catalog items -> ``connections``/``normalized_keys``; WEB becomes URL (idempotent)."""
    collection = db[catalog_repo.COLLECTION]
    count = 0
    for doc in collection.find({"connections": {"$exists": False}}):
        item = CatalogItem(**base_kwargs(doc))  # the model upgrades the legacy shape
        collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "connections": [c.model_dump(mode="json") for c in item.connections],
                    "normalized_keys": list(item.normalized_keys),
                },
                "$unset": dict.fromkeys(catalog_repo.LEGACY_FIELDS, ""),
            },
        )
        count += 1
    return f"moved {count} catalog item(s) to multi-protocol connections"


#: ``(step number, migration function)``, in order. Append new steps here; never renumber or
#: remove an applied one.
STEPS: tuple[tuple[int, MigrationFn], ...] = (
    (1, _step_1_default_zone_and_settings),
    (2, _step_2_catalog_connections),
)


def current_schema_version(db: Database[dict[str, Any]]) -> int:
    doc = db[SCHEMA_COLLECTION].find_one({"_id": SCHEMA_DOC_ID})
    return int(doc["version"]) if doc else 0


def run_migrations(db: Database[dict[str, Any]]) -> list[str]:
    """Apply every step beyond the current ``schema_meta`` version, in order. Idempotent."""
    applied: list[str] = []
    version = current_schema_version(db)
    for number, fn in STEPS:
        if number <= version:
            continue
        detail = fn(db)
        db[SCHEMA_COLLECTION].update_one(
            {"_id": SCHEMA_DOC_ID},
            {"$set": {"version": number, "migrated_at": utcnow()}},
            upsert=True,
        )
        version = number
        applied.append(f"step {number}: {detail}")
    return applied

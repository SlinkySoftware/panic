"""``catalog_items`` repository (DATA_MODEL.md §4.5)."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from panic_common.models import CatalogItem
from panic_common.visibility import VisibilitySpec
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
from panic_server.store.repos._scoped import find_visible

COLLECTION = "catalog_items"


def _to_model(doc: dict[str, Any]) -> CatalogItem:
    return CatalogItem(**base_kwargs(doc))


def create_catalog_item(
    db: Database[dict[str, Any]],
    *,
    title: str,
    protocol: str,
    host: str,
    normalized_key: str,
    created_by: str,
    description: str = "",
    port: int | None = None,
    site: str = "2SYA",
    path_or_args: str = "",
    custom_uri: str = "",
    account_override: str = "",
    tags: list[str] | None = None,
    scope: str = "GLOBAL",
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    zone_ids: list[str] | None = None,
    search_keys: list[str] | None = None,
    orphaned: bool = False,
) -> CatalogItem:
    now = utcnow()
    doc: dict[str, Any] = {
        "_id": new_id(),
        "title": title,
        "description": description,
        "protocol": protocol,
        "host": host,
        "site": site,
        "path_or_args": path_or_args,
        "custom_uri": custom_uri,
        "account_override": account_override,
        "tags": tags or [],
        "normalized_key": normalized_key,
        "scope": scope,
        "team_ids": team_ids or [],
        "owner_usernames": owner_usernames or [],
        "zone_ids": zone_ids or [],
        "search_keys": search_keys or [],
        "orphaned": orphaned,
        "created_by": created_by,
        "created_at": now,
        "updated_by": created_by,
        "updated_at": now,
        "version": 1,
    }
    if port is not None:
        doc["port"] = port
    return _to_model(insert_versioned(db[COLLECTION], doc))


def get_catalog_item(db: Database[dict[str, Any]], item_id: str) -> CatalogItem:
    return _to_model(get_or_404(db[COLLECTION], item_id))


def find_by_normalized_key(db: Database[dict[str, Any]], normalized_key: str, scope: str) -> CatalogItem | None:
    doc = db[COLLECTION].find_one({"normalized_key": normalized_key, "scope": scope})
    return _to_model(doc) if doc else None


def list_visible_catalog_items(
    db: Database[dict[str, Any]],
    spec: VisibilitySpec,
    *,
    extra_filter: dict[str, Any] | None = None,
) -> list[CatalogItem]:
    docs = find_visible(db, COLLECTION, spec, sort=[("scope", 1), ("title", 1)], extra_filter=extra_filter)
    return [_to_model(d) for d in docs]


def update_catalog_item(
    db: Database[dict[str, Any]],
    item_id: str,
    expected_version: int,
    *,
    updated_by: str,
    **fields: Any,
) -> CatalogItem:
    fields["updated_at"] = utcnow()
    fields["updated_by"] = updated_by
    doc = cas_update(db[COLLECTION], item_id, expected_version, {"$set": fields, "$inc": {"version": 1}})
    return _to_model(doc)


def delete_catalog_item(db: Database[dict[str, Any]], item_id: str, expected_version: int) -> None:
    delete_versioned(db[COLLECTION], item_id, expected_version)
    now = utcnow()
    db["endpoint_lists"].update_many(
        {"item_ids": item_id},
        {"$pull": {"item_ids": item_id}, "$inc": {"version": 1}, "$set": {"updated_at": now}},
    )


def list_all_catalog_items(db: Database[dict[str, Any]]) -> list[CatalogItem]:
    """Every catalog item regardless of visibility/orphan status (T-S6-03: admin export only)."""
    return [_to_model(d) for d in db[COLLECTION].find().sort("_id", 1)]


def upsert_catalog_item(db: Database[dict[str, Any]], model: CatalogItem) -> CatalogItem:
    """Insert-or-fully-replace a catalog item by ``model.id`` (T-S6-03: portable import)."""
    doc: dict[str, Any] = {
        "title": model.title,
        "description": model.description,
        "protocol": model.protocol,
        "host": model.host,
        "site": model.site,
        "path_or_args": model.path_or_args,
        "custom_uri": model.custom_uri,
        "account_override": model.account_override,
        "tags": list(model.tags),
        "normalized_key": model.normalized_key,
        "scope": model.scope,
        "team_ids": list(model.team_ids),
        "owner_usernames": list(model.owner_usernames),
        "zone_ids": list(model.zone_ids),
        "search_keys": list(model.search_keys),
        "orphaned": model.orphaned,
        "created_by": model.created_by,
        "created_at": from_iso_z(model.created_at),
        "updated_by": model.updated_by,
        "updated_at": from_iso_z(model.updated_at),
        "version": model.version,
    }
    update: dict[str, Any] = {"$set": doc}
    if model.port is not None:
        doc["port"] = model.port
    else:
        # Clear a previously-set port rather than leaving it stale (an existing doc may have one).
        update["$unset"] = {"port": ""}
    db[COLLECTION].update_one({"_id": model.id}, update, upsert=True)
    return model


def delete_all_catalog_items(db: Database[dict[str, Any]]) -> int:
    """Wipe every catalog item (``panic_seed --reset``). Returns the number deleted."""
    return db[COLLECTION].delete_many({}).deleted_count

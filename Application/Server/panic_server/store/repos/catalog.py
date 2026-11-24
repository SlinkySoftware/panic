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
#: Single-protocol fields replaced by ``connections``/``normalized_keys`` in 0.2 (migration step 2).
LEGACY_FIELDS = ("protocol", "port", "path_or_args", "custom_uri", "normalized_key")


def _to_model(doc: dict[str, Any]) -> CatalogItem:
    return CatalogItem(**base_kwargs(doc))


def create_catalog_item(
    db: Database[dict[str, Any]],
    *,
    title: str,
    host: str,
    connections: list[dict[str, Any]],
    normalized_keys: list[str],
    created_by: str,
    description: str = "",
    site: str = "2SYA",
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
        "host": host,
        "connections": connections,
        "site": site,
        "account_override": account_override,
        "tags": tags or [],
        "normalized_keys": normalized_keys,
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
    return _to_model(insert_versioned(db[COLLECTION], doc))


def get_catalog_item(db: Database[dict[str, Any]], item_id: str) -> CatalogItem:
    return _to_model(get_or_404(db[COLLECTION], item_id))


def find_by_normalized_keys(db: Database[dict[str, Any]], normalized_keys: list[str], scope: str) -> list[CatalogItem]:
    """Every item in ``scope`` sharing at least one connection key with ``normalized_keys``."""
    docs = db[COLLECTION].find({"normalized_keys": {"$in": normalized_keys}, "scope": scope}).limit(20)
    return [_to_model(d) for d in docs]


def get_catalog_items_by_ids(db: Database[dict[str, Any]], item_ids: list[str]) -> list[CatalogItem]:
    """Every catalog item in ``item_ids`` that still exists, in one round trip.

    Used by the dashboard/search read views to resolve many widget/list-referenced items without
    an N+1 ``get_catalog_item`` per id (API.md §8's Mongo round-trip budgets). Visibility is the
    caller's job (``panic_common.visibility.matches``), same as :func:`get_catalog_item`.
    """
    if not item_ids:
        return []
    return [_to_model(d) for d in db[COLLECTION].find({"_id": {"$in": item_ids}})]


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
    """Every catalog item regardless of visibility/orphan status (admin export only)."""
    return [_to_model(d) for d in db[COLLECTION].find().sort("_id", 1)]


def upsert_catalog_item(db: Database[dict[str, Any]], model: CatalogItem) -> CatalogItem:
    """Insert-or-fully-replace a catalog item by ``model.id`` (portable import)."""
    doc: dict[str, Any] = {
        "title": model.title,
        "description": model.description,
        "host": model.host,
        "connections": [c.model_dump(mode="json") for c in model.connections],
        "site": model.site,
        "account_override": model.account_override,
        "tags": list(model.tags),
        "normalized_keys": list(model.normalized_keys),
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
    # Clear pre-0.2 single-protocol fields an existing doc may still carry.
    update: dict[str, Any] = {"$set": doc, "$unset": dict.fromkeys(LEGACY_FIELDS, "")}
    db[COLLECTION].update_one({"_id": model.id}, update, upsert=True)
    return model


def delete_all_catalog_items(db: Database[dict[str, Any]]) -> int:
    """Wipe every catalog item (``panic_seed --reset``). Returns the number deleted."""
    return db[COLLECTION].delete_many({}).deleted_count


def rename_site_code(db: Database[dict[str, Any]], old_code: str, new_code: str) -> int:
    """``$set`` every item's ``site`` from ``old_code`` to ``new_code`` in one ``update_many``
    (DATA_MODEL.md §4.2: "renaming a code updates referencing items"). Returns the count touched."""
    if old_code == new_code:
        return 0
    result = db[COLLECTION].update_many({"site": old_code}, {"$set": {"site": new_code}})
    return result.modified_count

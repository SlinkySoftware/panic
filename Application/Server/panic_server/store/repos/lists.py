"""``endpoint_lists`` repository (DATA_MODEL.md §4.6)."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from panic_common.models import EndpointList
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

COLLECTION = "endpoint_lists"


def _to_model(doc: dict[str, Any]) -> EndpointList:
    return EndpointList(**base_kwargs(doc))


def create_list(
    db: Database[dict[str, Any]],
    *,
    title: str,
    created_by: str,
    description: str = "",
    scope: str = "GLOBAL",
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    item_ids: list[str] | None = None,
    search_keys: list[str] | None = None,
    orphaned: bool = False,
) -> EndpointList:
    now = utcnow()
    doc: dict[str, Any] = {
        "_id": new_id(),
        "title": title,
        "description": description,
        "scope": scope,
        "team_ids": team_ids or [],
        "owner_usernames": owner_usernames or [],
        "item_ids": item_ids or [],
        "search_keys": search_keys or [],
        "orphaned": orphaned,
        "created_by": created_by,
        "created_at": now,
        "updated_by": created_by,
        "updated_at": now,
        "version": 1,
    }
    return _to_model(insert_versioned(db[COLLECTION], doc))


def get_list(db: Database[dict[str, Any]], list_id: str) -> EndpointList:
    return _to_model(get_or_404(db[COLLECTION], list_id))


def get_lists_by_ids(db: Database[dict[str, Any]], list_ids: list[str]) -> list[EndpointList]:
    """Every list in ``list_ids`` that still exists, in one round trip (T-S6-06).

    Sibling of ``catalog.get_catalog_items_by_ids``; same rationale (API.md §8 round-trip budgets
    for the dashboard read view, which may reference up to a dozen lists).
    """
    if not list_ids:
        return []
    return [_to_model(d) for d in db[COLLECTION].find({"_id": {"$in": list_ids}})]


def list_visible_lists(
    db: Database[dict[str, Any]],
    spec: VisibilitySpec,
    *,
    extra_filter: dict[str, Any] | None = None,
) -> list[EndpointList]:
    docs = find_visible(db, COLLECTION, spec, sort=[("scope", 1), ("title", 1)], extra_filter=extra_filter)
    return [_to_model(d) for d in docs]


def update_list(
    db: Database[dict[str, Any]],
    list_id: str,
    expected_version: int,
    *,
    updated_by: str,
    **fields: Any,
) -> EndpointList:
    fields["updated_at"] = utcnow()
    fields["updated_by"] = updated_by
    doc = cas_update(db[COLLECTION], list_id, expected_version, {"$set": fields, "$inc": {"version": 1}})
    return _to_model(doc)


def delete_list(db: Database[dict[str, Any]], list_id: str, expected_version: int) -> None:
    delete_versioned(db[COLLECTION], list_id, expected_version)


def list_all_lists(db: Database[dict[str, Any]]) -> list[EndpointList]:
    """Every list regardless of visibility/orphan status (T-S6-03: admin export only)."""
    return [_to_model(d) for d in db[COLLECTION].find().sort("_id", 1)]


def upsert_list(db: Database[dict[str, Any]], model: EndpointList) -> EndpointList:
    """Insert-or-fully-replace a list by ``model.id`` (T-S6-03: portable import)."""
    doc: dict[str, Any] = {
        "title": model.title,
        "description": model.description,
        "scope": model.scope,
        "team_ids": list(model.team_ids),
        "owner_usernames": list(model.owner_usernames),
        "item_ids": list(model.item_ids),
        "search_keys": list(model.search_keys),
        "orphaned": model.orphaned,
        "created_by": model.created_by,
        "created_at": from_iso_z(model.created_at),
        "updated_by": model.updated_by,
        "updated_at": from_iso_z(model.updated_at),
        "version": model.version,
    }
    db[COLLECTION].update_one({"_id": model.id}, {"$set": doc}, upsert=True)
    return model


def delete_all_lists(db: Database[dict[str, Any]]) -> int:
    """Wipe every list (``panic_seed --reset``). Returns the number deleted."""
    return db[COLLECTION].delete_many({}).deleted_count

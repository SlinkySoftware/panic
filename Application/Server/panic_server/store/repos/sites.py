"""``sites`` repository (DATA_MODEL.md §4.2)."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from panic_common.models import SiteDefinition
from panic_server.store.cas import (
    base_kwargs,
    cas_update,
    delete_versioned,
    get_or_404,
    insert_versioned,
    new_id,
    utcnow,
)

COLLECTION = "sites"


def _to_model(doc: dict[str, Any]) -> SiteDefinition:
    return SiteDefinition(**base_kwargs(doc))


def create_site(db: Database[dict[str, Any]], *, code: str, name: str, description: str = "") -> SiteDefinition:
    now = utcnow()
    doc = {
        "_id": new_id(),
        "code": code.upper(),
        "name": name,
        "description": description,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    return _to_model(insert_versioned(db[COLLECTION], doc))


def get_site(db: Database[dict[str, Any]], site_id: str) -> SiteDefinition:
    return _to_model(get_or_404(db[COLLECTION], site_id))


def get_site_by_code(db: Database[dict[str, Any]], code: str) -> SiteDefinition | None:
    doc = db[COLLECTION].find_one({"code": code.upper()})
    return _to_model(doc) if doc else None


def list_sites(db: Database[dict[str, Any]]) -> list[SiteDefinition]:
    return [_to_model(d) for d in db[COLLECTION].find().sort("code", 1)]


def update_site(
    db: Database[dict[str, Any]],
    site_id: str,
    expected_version: int,
    *,
    code: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> SiteDefinition:
    fields: dict[str, Any] = {"updated_at": utcnow()}
    if code is not None:
        fields["code"] = code.upper()
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description
    doc = cas_update(db[COLLECTION], site_id, expected_version, {"$set": fields, "$inc": {"version": 1}})
    return _to_model(doc)


def delete_site(db: Database[dict[str, Any]], site_id: str, expected_version: int) -> None:
    delete_versioned(db[COLLECTION], site_id, expected_version)

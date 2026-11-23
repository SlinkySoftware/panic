"""``teams`` repository (DATA_MODEL.md §4.3).

Membership is not stored here. ``TeamDefinition.members`` keeps its pydantic default (``[]``);
a team's members are ``users.find({team_ids: <id>})`` (a service/API-layer concern, not this repo).
"""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from panic_common.models import TeamDefinition
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

COLLECTION = "teams"


def _to_model(doc: dict[str, Any]) -> TeamDefinition:
    return TeamDefinition(**base_kwargs(doc))


def create_team(db: Database[dict[str, Any]], *, code: str, name: str, description: str = "") -> TeamDefinition:
    now = utcnow()
    doc = {
        "_id": new_id(),
        "code": code,
        "name": name,
        "description": description,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    return _to_model(insert_versioned(db[COLLECTION], doc))


def get_team(db: Database[dict[str, Any]], team_id: str) -> TeamDefinition:
    return _to_model(get_or_404(db[COLLECTION], team_id))


def get_team_by_code(db: Database[dict[str, Any]], code: str) -> TeamDefinition | None:
    doc = db[COLLECTION].find_one({"code": code})
    return _to_model(doc) if doc else None


def list_teams(db: Database[dict[str, Any]]) -> list[TeamDefinition]:
    return [_to_model(d) for d in db[COLLECTION].find().sort("name", 1)]


def update_team(
    db: Database[dict[str, Any]],
    team_id: str,
    expected_version: int,
    *,
    code: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> TeamDefinition:
    fields: dict[str, Any] = {"updated_at": utcnow()}
    if code is not None:
        fields["code"] = code
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description
    doc = cas_update(db[COLLECTION], team_id, expected_version, {"$set": fields, "$inc": {"version": 1}})
    return _to_model(doc)


def delete_team(db: Database[dict[str, Any]], team_id: str, expected_version: int) -> dict[str, int]:
    """Delete a team, ``$pull`` its id from every reference, and orphan TEAM resources left bare.

    Returns the number of documents touched in each affected collection (``users``, and
    ``<collection>``/``<collection>_orphaned`` for each of the three scoped collections), for the
    caller to report (API.md §4.7: ``200 {orphaned: {catalog, lists, dashboards}}``).
    """
    delete_versioned(db[COLLECTION], team_id, expected_version)
    counts: dict[str, int] = {}
    users_result = db["users"].update_many({"team_ids": team_id}, {"$pull": {"team_ids": team_id}})
    counts["users"] = users_result.modified_count
    for collection in ("catalog_items", "endpoint_lists", "dashboards"):
        pulled = db[collection].update_many(
            {"team_ids": team_id},
            {"$pull": {"team_ids": team_id}, "$inc": {"version": 1}, "$set": {"updated_at": utcnow()}},
        )
        counts[collection] = pulled.modified_count
        orphaned = db[collection].update_many(
            {"scope": "TEAM", "team_ids": [], "orphaned": {"$ne": True}},
            {"$set": {"orphaned": True}, "$inc": {"version": 1}},
        )
        counts[f"{collection}_orphaned"] = orphaned.modified_count
    return counts


def upsert_team(db: Database[dict[str, Any]], model: TeamDefinition) -> TeamDefinition:
    """Insert-or-fully-replace a team by ``model.id``. ``members`` is never stored."""
    doc = {
        "code": model.code,
        "name": model.name,
        "description": model.description,
        "created_at": from_iso_z(model.created_at),
        "updated_at": from_iso_z(model.updated_at),
        "version": model.version,
    }
    db[COLLECTION].update_one({"_id": model.id}, {"$set": doc}, upsert=True)
    return model


def delete_all_teams(db: Database[dict[str, Any]]) -> int:
    """Wipe every team (``panic_seed --reset``). Returns the number deleted."""
    return db[COLLECTION].delete_many({}).deleted_count

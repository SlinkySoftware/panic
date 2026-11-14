"""``users`` repository (DATA_MODEL.md §4.1).

Preferences are stored nested (``prefs: {density, theme, unreachable_policy}``) as specified in
DATA_MODEL.md, but ``panic_common.models.UserAccount`` carries them as flat fields; this module
translates both ways. ``password_hash`` (LOCAL auth only) is written and read here but never
appears on ``UserAccount`` (pydantic silently ignores the unknown constructor kwarg), so it can
never leak past this module.
"""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from panic_common.models import UserAccount
from panic_server.store.cas import base_kwargs, cas_update, get_or_404, insert_versioned, new_id, utcnow

COLLECTION = "users"
_PREFS_FIELDS = ("density", "theme", "unreachable_policy")


def _to_model(doc: dict[str, Any]) -> UserAccount:
    kwargs = base_kwargs(doc)
    prefs = kwargs.pop("prefs", None) or {}
    for field_name in _PREFS_FIELDS:
        if field_name in prefs:
            kwargs[field_name] = prefs[field_name]
    return UserAccount(**kwargs)


def create_user(
    db: Database[dict[str, Any]],
    *,
    username: str,
    display_name: str,
    default_remote_user: str,
    auth_source: str = "LOCAL",
    password_hash: str | None = None,
    ssh_template: str = "ssh {user}@{host} -p {port} {flags}",
    permissions: list[str] | None = None,
    team_ids: list[str] | None = None,
    search_keys: list[str] | None = None,
) -> UserAccount:
    now = utcnow()
    doc: dict[str, Any] = {
        "_id": new_id(),
        "username": username,
        "display_name": display_name,
        "default_remote_user": default_remote_user,
        "ssh_template": ssh_template,
        "auth_source": auth_source,
        "disabled": False,
        "permissions": permissions or [],
        "team_ids": team_ids or [],
        "pinned_dashboard_ids": [],
        "default_dashboard_id": None,
        "prefs": {"density": "COMFORT", "theme": "DARK", "unreachable_policy": "DIM"},
        "search_keys": search_keys or [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    if password_hash is not None:
        doc["password_hash"] = password_hash
    return _to_model(insert_versioned(db[COLLECTION], doc))


def get_user(db: Database[dict[str, Any]], user_id: str) -> UserAccount:
    return _to_model(get_or_404(db[COLLECTION], user_id))


def get_user_by_username(db: Database[dict[str, Any]], username: str) -> UserAccount | None:
    doc = db[COLLECTION].find_one({"username": username})
    return _to_model(doc) if doc else None


def get_password_hash(db: Database[dict[str, Any]], username: str) -> str | None:
    """The raw password hash for LOCAL auth -- the one field intentionally excluded from the model."""
    doc = db[COLLECTION].find_one({"username": username}, {"password_hash": 1})
    return doc.get("password_hash") if doc else None


def list_users(
    db: Database[dict[str, Any]],
    *,
    team_id: str | None = None,
    permission: str | None = None,
    disabled: bool | None = None,
) -> list[UserAccount]:
    query: dict[str, Any] = {}
    if team_id is not None:
        query["team_ids"] = team_id
    if permission is not None:
        query["permissions"] = permission
    if disabled is not None:
        query["disabled"] = disabled
    return [_to_model(d) for d in db[COLLECTION].find(query).sort("username", 1)]


def count_enabled_admins(db: Database[dict[str, Any]]) -> int:
    return db[COLLECTION].count_documents({"disabled": False, "permissions": "GLOBAL_ADMIN"})


def update_user(
    db: Database[dict[str, Any]],
    user_id: str,
    expected_version: int,
    **fields: Any,
) -> UserAccount:
    """Update any subset of the mutable fields; ``density``/``theme``/``unreachable_policy``
    are written back under the nested ``prefs`` document."""
    set_fields: dict[str, Any] = {"updated_at": utcnow()}
    prefs_update = {k: fields.pop(k) for k in _PREFS_FIELDS if k in fields}
    for key, value in prefs_update.items():
        set_fields[f"prefs.{key}"] = value
    set_fields.update(fields)
    doc = cas_update(db[COLLECTION], user_id, expected_version, {"$set": set_fields, "$inc": {"version": 1}})
    return _to_model(doc)

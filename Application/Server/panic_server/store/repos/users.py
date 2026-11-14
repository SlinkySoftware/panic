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
from panic_server.store.cas import base_kwargs, cas_update, from_iso_z, get_or_404, insert_versioned, new_id, utcnow

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


def set_password_hash(
    db: Database[dict[str, Any]],
    username: str,
    password_hash: str,
    *,
    auth_source: str | None = None,
) -> None:
    """Set the raw LOCAL-auth password hash for ``username`` (T-S6-04).

    Not CAS-protected: ``password_hash`` is never exposed on :class:`UserAccount`, so there is no
    client-visible ``version`` for a concurrent editor to race against.
    """
    fields: dict[str, Any] = {"password_hash": password_hash, "updated_at": utcnow()}
    if auth_source is not None:
        fields["auth_source"] = auth_source
    db[COLLECTION].update_one({"username": username}, {"$set": fields})


def touch_last_login(db: Database[dict[str, Any]], user_id: str, *, display_name: str | None = None) -> None:
    """Record a successful sign-in: ``last_login_at`` (DATA_MODEL.md §4.1) and, optionally, ``display_name``.

    Used on every successful local/OIDC/LDAP sign-in. Deliberately not CAS-protected and never
    touches ``permissions``/``team_ids`` (ADR-0001 decision 11: re-sign-in never re-syncs RBAC).
    """
    fields: dict[str, Any] = {"last_login_at": utcnow()}
    if display_name is not None:
        fields["display_name"] = display_name
    db[COLLECTION].update_one({"_id": user_id}, {"$set": fields})


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


def upsert_user(db: Database[dict[str, Any]], model: UserAccount) -> UserAccount:
    """Insert-or-fully-replace a user by ``model.id`` (T-S6-03: portable import, byte-stable).

    Never touches ``password_hash``: it is not on :class:`UserAccount` to begin with, and using
    ``$set`` (not a whole-document ``replace_one``) leaves any existing hash on the stored
    document untouched.
    """
    doc: dict[str, Any] = {
        "username": model.username,
        "display_name": model.display_name,
        "default_remote_user": model.default_remote_user,
        "ssh_template": model.ssh_template,
        "auth_source": model.auth_source,
        "disabled": model.disabled,
        "permissions": list(model.permissions),
        "team_ids": list(model.team_ids),
        "pinned_dashboard_ids": list(model.pinned_dashboard_ids),
        "default_dashboard_id": model.default_dashboard_id,
        "prefs": {
            "density": model.density,
            "theme": model.theme,
            "unreachable_policy": model.unreachable_policy,
        },
        "search_keys": list(model.search_keys),
        "updated_at": from_iso_z(model.updated_at),
        "version": model.version,
    }
    update: dict[str, Any] = {"$set": doc}
    if model.last_login_at is not None:
        doc["last_login_at"] = from_iso_z(model.last_login_at)
    else:
        update["$unset"] = {"last_login_at": ""}
    db[COLLECTION].update_one({"_id": model.id}, update, upsert=True)
    return model


def delete_all_users(db: Database[dict[str, Any]]) -> int:
    """Wipe every user (``panic_seed --reset``). Returns the number deleted."""
    return db[COLLECTION].delete_many({}).deleted_count


def remove_dashboard_references(db: Database[dict[str, Any]], dashboard_id: str) -> int:
    """``$pull`` ``dashboard_id`` from every user's pins and clear it as their default (T-S6-07).

    Called by the dashboard-delete cascade (API.md §4.3: "removes it from users' pins/defaults").
    Not CAS-protected: like ``touch_last_login``, this never touches a field a concurrent editor
    of the *user* document would race on (``permissions``/``team_ids``/etc.), only the two
    dashboard-reference fields, so a plain ``update_many`` is safe and avoids a per-user CAS loop.
    """
    pulled = db[COLLECTION].update_many(
        {"pinned_dashboard_ids": dashboard_id}, {"$pull": {"pinned_dashboard_ids": dashboard_id}}
    )
    unset = db[COLLECTION].update_many({"default_dashboard_id": dashboard_id}, {"$set": {"default_dashboard_id": None}})
    return pulled.modified_count + unset.modified_count

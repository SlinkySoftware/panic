"""Declarative portable JSON export / import of the Mongo-backed portal state.

The format is ``schema_version: 2``. Reads and writes go only through
``panic_server.store.repos.*`` (never a raw pymongo document) so the never-export rules -- no
password hashes, no sessions, no rate limits, no audit log -- hold structurally:
``UserAccount`` has no ``password_hash`` field to begin with, and the other three collections
are simply never in ``_SECTIONS``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from panic_common.models import (
    CatalogItem,
    Dashboard,
    EndpointList,
    ScopeType,
    SecurityZone,
    SiteDefinition,
    SystemSettings,
    TeamDefinition,
    UserAccount,
)
from panic_server import __version__
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

EXPORT_FORMAT = "panic-export"
EXPORT_SCHEMA_VERSION = 2

#: ``section name -> pydantic model``, in the order they appear in an export document.
_SECTIONS: dict[str, type[Any]] = {
    "sites": SiteDefinition,
    "teams": TeamDefinition,
    "zones": SecurityZone,
    "users": UserAccount,
    "catalog": CatalogItem,
    "lists": EndpointList,
    "dashboards": Dashboard,
}

#: ``section name -> (list-everything, upsert-by-id)`` repo functions.
_REPOS: dict[str, tuple[Any, Any]] = {
    "sites": (sites_repo.list_sites, sites_repo.upsert_site),
    "teams": (teams_repo.list_teams, teams_repo.upsert_team),
    "zones": (zones_repo.list_zones, zones_repo.upsert_zone),
    "users": (users_repo.list_users, users_repo.upsert_user),
    "catalog": (catalog_repo.list_all_catalog_items, catalog_repo.upsert_catalog_item),
    "lists": (lists_repo.list_all_lists, lists_repo.upsert_list),
    "dashboards": (dashboards_repo.list_all_dashboards, dashboards_repo.upsert_dashboard),
}

_WIPE_FNS: tuple[Any, ...] = (
    sites_repo.delete_all_sites,
    teams_repo.delete_all_teams,
    zones_repo.delete_all_zones,
    users_repo.delete_all_users,
    catalog_repo.delete_all_catalog_items,
    lists_repo.delete_all_lists,
    dashboards_repo.delete_all_dashboards,
    settings_repo.delete_system_settings,
)


class ImportValidationError(ValueError):
    """Raised when an import document is malformed or of an unsupported schema version."""


def _ensure_scaffolding(db: Any) -> None:
    """The built-in Default zone and the ``system`` settings doc must always exist (§4.13)."""
    zones_repo.ensure_default_zone(db)
    settings_repo.ensure_system_settings(db, default_global_dashboard_id="", updated_by="system")


def wipe_all(db: Any) -> None:
    """Delete every document in every exportable collection, then restore the built-in scaffolding.

    Used by ``panic_seed --reset`` and ``panic_import --replace``.
    """
    for wipe in _WIPE_FNS:
        wipe(db)
    _ensure_scaffolding(db)


def export_state(db: Any, shared_only: bool = False) -> dict[str, Any]:
    """Build a ``schema_version: 2`` export document.

    Each section is sorted by ``id`` so that export -> import -> export is byte-stable
    (except ``exported_at``). ``shared_only`` drops users and every PERSONAL-scoped catalog
    item, list and dashboard. Password hashes, sessions, rate limits and the audit log are
    never included (there is no section for them, and ``UserAccount`` has no password field).
    """
    doc: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "schema_version": EXPORT_SCHEMA_VERSION,
        "server_version": __version__,
        "exported_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "shared_only": shared_only,
    }
    for section, (list_all, _upsert) in _REPOS.items():
        objs = [] if (shared_only and section == "users") else list(list_all(db))
        if shared_only and section in {"catalog", "lists", "dashboards"}:
            objs = [o for o in objs if o.scope != ScopeType.PERSONAL]
        dumped = [o.model_dump(mode="json") for o in objs]
        dumped.sort(key=lambda o: o["id"])
        doc[section] = dumped
    settings_doc = settings_repo.get_system_settings(db)
    doc["system_settings"] = settings_doc.model_dump(mode="json") if settings_doc else None
    return doc


def _parse(doc: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get("format") != EXPORT_FORMAT:
        raise ImportValidationError("not a PANIC export document")
    if doc.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise ImportValidationError(f"unsupported schema_version {doc.get('schema_version')!r}")
    parsed: dict[str, Any] = {}
    try:
        for section, model in _SECTIONS.items():
            parsed[section] = [model.model_validate(o) for o in doc.get(section, [])]
        raw_settings = doc.get("system_settings")
        parsed["system_settings"] = SystemSettings.model_validate(raw_settings) if raw_settings else None
    except ValueError as e:
        raise ImportValidationError(str(e)) from e
    return parsed


def import_state(db: Any, doc: dict[str, Any], replace: bool = False) -> dict[str, int]:
    """Load a ``schema_version: 2`` export document. Entities are upserted by id.

    ``replace=True`` wipes every exportable collection first (destructive); otherwise existing
    documents are overwritten in place by id and unrelated documents are left untouched.
    """
    parsed = _parse(doc)
    if replace:
        wipe_all(db)
    else:
        _ensure_scaffolding(db)
    counts: dict[str, int] = {}
    for section, (_list_all, upsert) in _REPOS.items():
        for obj in parsed[section]:
            upsert(db, obj)
        counts[section] = len(parsed[section])
    if parsed["system_settings"] is not None:
        settings_repo.upsert_system_settings(db, parsed["system_settings"])
    return counts

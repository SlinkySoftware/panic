"""Declarative portable JSON export / import of portal state (T-S2-03).

The document is versioned and contains only ``panic_common`` model dumps, never secrets
(password hashes and identity-provider bindings are excluded).
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
from panic_server.store_db import DatabasePortalStore

EXPORT_FORMAT = "panic-export"
EXPORT_SCHEMA_VERSION = 1

_SECTIONS: dict[str, type[Any]] = {
    "sites": SiteDefinition,
    "teams": TeamDefinition,
    "zones": SecurityZone,
    "users": UserAccount,
    "catalog": CatalogItem,
    "lists": EndpointList,
    "dashboards": Dashboard,
}


class ImportValidationError(ValueError):
    """Raised when an import document is malformed or of an unsupported schema version."""


def export_state(store: DatabasePortalStore, shared_only: bool = False) -> dict[str, Any]:
    """Serialize the store to a portable document.

    ``shared_only`` drops users and every ``PERSONAL``-scoped catalog item, list, and dashboard.
    """
    with store._lock:
        store.ensure_loaded()
        doc: dict[str, Any] = {
            "format": EXPORT_FORMAT,
            "schema_version": EXPORT_SCHEMA_VERSION,
            "server_version": __version__,
            "exported_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "shared_only": shared_only,
        }
        for section in _SECTIONS:
            objs = list(getattr(store, section))
            if shared_only:
                if section == "users":
                    objs = []
                elif section in {"catalog", "lists", "dashboards"}:
                    objs = [o for o in objs if o.scope != ScopeType.PERSONAL]
            doc[section] = [o.model_dump(mode="json") for o in objs]
        doc["system_settings"] = store.system_settings.model_dump(mode="json")
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


def import_state(store: DatabasePortalStore, doc: dict[str, Any], replace: bool = False) -> dict[str, int]:
    """Upsert every entity in ``doc`` (matched by id). ``replace=True`` wipes the database first."""
    parsed = _parse(doc)
    with store._lock:
        if replace:
            store.wipe()
            store.refresh()
        else:
            store.ensure_loaded()
        counts: dict[str, int] = {}
        for section in _SECTIONS:
            current = {o.id: idx for idx, o in enumerate(getattr(store, section))}
            target = getattr(store, section)
            for obj in parsed[section]:
                if obj.id in current:
                    target[current[obj.id]] = obj
                else:
                    target.append(obj)
            counts[section] = len(parsed[section])
        if parsed["system_settings"] is not None:
            store.system_settings = parsed["system_settings"]
        store.persist()
        store.refresh()
        return counts

"""Index definitions for the PANIC database (DATA_MODEL.md §4).

Applied by ``manage.py panic_ensure_indexes`` (idempotent; run by ``panic setup``/``panic test``
and container start). Every index has an explicit name so re-runs are no-ops and a changed
definition is detected instead of silently duplicated or silently ignored.

The one documented exception to "different definition = error" is the ``audit_log`` and
``sessions``/``rate_limits`` TTL indexes: when only ``expireAfterSeconds`` changed, ``collMod``
updates it in place (DATA_MODEL.md §4.9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database
from pymongo.errors import OperationFailure

IndexKeys = list[tuple[str, int]]


@dataclass(frozen=True)
class IndexSpec:
    collection: str
    name: str
    keys: IndexKeys
    options: dict[str, Any] = field(default_factory=dict)

    def model(self) -> IndexModel:
        return IndexModel(self.keys, name=self.name, **self.options)


def _i(collection: str, name: str, keys: IndexKeys, **options: Any) -> IndexSpec:
    return IndexSpec(collection, name, keys, options)


A, D = ASCENDING, DESCENDING

#: Name of the audit_log TTL index; built dynamically since its expireAfterSeconds is configurable
#: and a retention of 0 means "no TTL index at all" (DATA_MODEL.md §4.9).
AUDIT_TTL_INDEX_NAME = "created_at_ttl"

INDEXES: tuple[IndexSpec, ...] = (
    # users (DATA_MODEL §4.1)
    _i("users", "username_unique", [("username", A)], unique=True),
    _i("users", "team_ids", [("team_ids", A)]),
    _i("users", "permissions", [("permissions", A)]),
    _i("users", "disabled", [("disabled", A)]),
    _i("users", "search_keys", [("search_keys", A)]),
    # sites (§4.2)
    _i("sites", "code_unique", [("code", A)], unique=True),
    # teams (§4.3)
    _i("teams", "code_unique", [("code", A)], unique=True),
    # zones (§4.4)
    _i("zones", "name_unique", [("name", A)], unique=True),
    # catalog_items (§4.5)
    _i("catalog_items", "scope_team_title", [("scope", A), ("team_ids", A), ("title", A)]),
    _i("catalog_items", "scope_owner_title", [("scope", A), ("owner_usernames", A), ("title", A)]),
    _i("catalog_items", "scope_title", [("scope", A), ("title", A)]),
    _i("catalog_items", "normalized_key_scope", [("normalized_key", A), ("scope", A)]),
    _i("catalog_items", "search_keys", [("search_keys", A)]),
    _i("catalog_items", "protocol", [("protocol", A)]),
    _i("catalog_items", "site", [("site", A)]),
    _i("catalog_items", "zone_ids", [("zone_ids", A)]),
    _i("catalog_items", "orphaned_scope", [("orphaned", A), ("scope", A)]),
    # endpoint_lists (§4.6)
    _i("endpoint_lists", "scope_team_title", [("scope", A), ("team_ids", A), ("title", A)]),
    _i("endpoint_lists", "scope_owner_title", [("scope", A), ("owner_usernames", A), ("title", A)]),
    _i("endpoint_lists", "scope_title", [("scope", A), ("title", A)]),
    _i("endpoint_lists", "item_ids", [("item_ids", A)]),
    _i("endpoint_lists", "search_keys", [("search_keys", A)]),
    _i("endpoint_lists", "orphaned_scope", [("orphaned", A), ("scope", A)]),
    # dashboards (§4.7)
    _i("dashboards", "scope_team_sort", [("scope", A), ("team_ids", A), ("sort_order", A)]),
    _i("dashboards", "scope_owner_sort", [("scope", A), ("owner_usernames", A), ("sort_order", A)]),
    _i("dashboards", "scope_always_sort", [("scope", A), ("always_display", A), ("sort_order", A)]),
    _i("dashboards", "widgets_catalog_item_id", [("widgets.catalog_item_id", A)]),
    _i("dashboards", "widgets_list_id", [("widgets.list_id", A)]),
    _i("dashboards", "search_keys", [("search_keys", A)]),
    _i("dashboards", "orphaned_scope", [("orphaned", A), ("scope", A)]),
    # audit_log (§4.9) - TTL index appended dynamically by ensure_indexes()
    _i("audit_log", "created_at_id_desc", [("created_at", D), ("_id", D)]),
    _i("audit_log", "actor_created_desc", [("actor_username", A), ("created_at", D)]),
    _i("audit_log", "action_created_desc", [("action", A), ("created_at", D)]),
    _i("audit_log", "target_created_desc", [("target_type", A), ("target_id", A), ("created_at", D)]),
    # sessions (§4.11, AR-4.7)
    _i("sessions", "expire_at_ttl", [("expire_at", A)], expireAfterSeconds=0),
    _i("sessions", "uid", [("uid", A)]),
    # rate_limits (§4.12) - the window start is part of _id; TTL just sweeps old windows
    _i("rate_limits", "expire_at_ttl", [("expire_at", A)], expireAfterSeconds=0),
)


OBSOLETE: tuple[tuple[str, str], ...] = ()
"""``(collection, index name)`` pairs that earlier versions created; ``ensure_indexes`` drops them."""


@dataclass
class EnsureReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


def _same_keys(existing: dict[str, Any], spec: IndexSpec) -> bool:
    return [tuple(k) for k in existing.get("key", [])] == [tuple(k) for k in spec.keys]


def _same(existing: dict[str, Any], spec: IndexSpec) -> bool:
    if not _same_keys(existing, spec):
        return False
    return all(existing.get(opt) == value for opt, value in spec.options.items())


def _same_ignoring_ttl(existing: dict[str, Any], spec: IndexSpec) -> bool:
    """Same keys and every option but ``expireAfterSeconds`` match (the ``collMod`` case)."""
    if not _same_keys(existing, spec):
        return False
    return all(existing.get(opt) == value for opt, value in spec.options.items() if opt != "expireAfterSeconds")


def _audit_ttl_spec() -> IndexSpec | None:
    """The audit_log TTL IndexSpec for the current ``PANIC_AUDIT_RETENTION_DAYS``, or None if disabled."""
    days = int(settings.PANIC_AUDIT_RETENTION_DAYS)
    if days <= 0:
        return None
    return _i("audit_log", AUDIT_TTL_INDEX_NAME, [("created_at", A)], expireAfterSeconds=days * 86400)


def ensure_indexes(db: Database[dict[str, Any]]) -> EnsureReport:
    """Create every missing index in :data:`INDEXES` (plus the audit TTL index). Idempotent.

    Raises :class:`RuntimeError` if an index with the same name exists with a different
    definition (a deliberate change must drop it first) -- except a changed
    ``expireAfterSeconds`` on a TTL index, which is applied in place with ``collMod``.
    """
    report = EnsureReport()
    for collection, name in OBSOLETE:
        try:
            info = db[collection].index_information()
        except OperationFailure:
            continue
        if name in info:
            db[collection].drop_index(name)
            report.dropped.append(f"{collection}.{name}")

    specs = list(INDEXES)
    audit_spec = _audit_ttl_spec()
    if audit_spec is not None:
        specs.append(audit_spec)
    else:
        # Retention disabled (0): make sure no stale TTL index from an earlier nonzero setting remains.
        try:
            audit_info = db["audit_log"].index_information()
        except OperationFailure:
            audit_info = {}
        if AUDIT_TTL_INDEX_NAME in audit_info:
            db["audit_log"].drop_index(AUDIT_TTL_INDEX_NAME)
            report.dropped.append(f"audit_log.{AUDIT_TTL_INDEX_NAME}")

    by_collection: dict[str, list[IndexSpec]] = {}
    for spec in specs:
        by_collection.setdefault(spec.collection, []).append(spec)

    for collection, col_specs in by_collection.items():
        try:
            info = db[collection].index_information()
        except OperationFailure:
            info = {}
        missing: list[IndexSpec] = []
        for spec in col_specs:
            label = f"{collection}.{spec.name}"
            if spec.name in info:
                existing = info[spec.name]
                if _same(existing, spec):
                    report.existing.append(label)
                elif "expireAfterSeconds" in spec.options and _same_ignoring_ttl(existing, spec):
                    db.command(
                        "collMod",
                        collection,
                        index={"keyPattern": dict(spec.keys), "expireAfterSeconds": spec.options["expireAfterSeconds"]},
                    )
                    report.changed.append(label)
                else:
                    raise RuntimeError(f"index {label} exists with a different definition; drop it first")
            else:
                missing.append(spec)
        if missing:
            db[collection].create_indexes([s.model() for s in missing])
            report.created.extend(f"{collection}.{s.name}" for s in missing)
    return report

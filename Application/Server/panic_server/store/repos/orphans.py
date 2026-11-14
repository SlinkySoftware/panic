"""Orphan flag maintenance and queries, shared across the three scoped collections
(DATA_MODEL.md §5.1): ``catalog_items``, ``endpoint_lists``, ``dashboards``.

Recomputation on a user disable/enable is a later task's call site (the service layer); this
module provides the primitive so that task doesn't touch ``panic_server.store`` internals.
"""

from __future__ import annotations

from collections.abc import Collection as CollectionABC
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database

from panic_server.store.cas import cas_update, utcnow

SCOPED_COLLECTIONS = ("catalog_items", "endpoint_lists", "dashboards")


def list_orphans(db: Database[dict[str, Any]], collection: str) -> list[dict[str, Any]]:
    """Raw orphaned documents in ``collection`` (admin-only view; caller maps to its own model)."""
    if collection not in SCOPED_COLLECTIONS:
        raise ValueError(f"not a scoped collection: {collection!r}")
    return list(db[collection].find({"orphaned": True}))


def set_orphaned(
    db: Database[dict[str, Any]],
    collection: str,
    doc_id: str,
    orphaned: bool,
    expected_version: int,
) -> dict[str, Any]:
    if collection not in SCOPED_COLLECTIONS:
        raise ValueError(f"not a scoped collection: {collection!r}")
    return cas_update(
        db[collection],
        doc_id,
        expected_version,
        {"$set": {"orphaned": orphaned, "updated_at": utcnow()}, "$inc": {"version": 1}},
    )


def _coll(db: Database[dict[str, Any]], collection: str) -> Collection[dict[str, Any]]:
    if collection not in SCOPED_COLLECTIONS:
        raise ValueError(f"not a scoped collection: {collection!r}")
    return db[collection]


def recompute_orphans_on_user_change(
    db: Database[dict[str, Any]], enabled_usernames: CollectionABC[str]
) -> dict[str, int]:
    """Re-derive ``orphaned`` on every PERSONAL document after a user was disabled or enabled.

    A PERSONAL document is orphaned iff none of its ``owner_usernames`` is in
    ``enabled_usernames`` (``panic_common.visibility.is_orphan``). Call after flipping a user's
    ``disabled`` flag with the fresh, complete set of currently-enabled usernames.
    """
    enabled = list(enabled_usernames)
    counts: dict[str, int] = {}
    for collection in SCOPED_COLLECTIONS:
        coll = _coll(db, collection)
        now_orphaned = coll.update_many(
            {
                "scope": "PERSONAL",
                "orphaned": {"$ne": True},
                "owner_usernames": {"$not": {"$elemMatch": {"$in": enabled}}},
            },
            {"$set": {"orphaned": True}, "$inc": {"version": 1}},
        )
        now_unorphaned = coll.update_many(
            {
                "scope": "PERSONAL",
                "orphaned": True,
                "owner_usernames": {"$elemMatch": {"$in": enabled}},
            },
            {"$set": {"orphaned": False}, "$inc": {"version": 1}},
        )
        counts[collection] = now_orphaned.modified_count + now_unorphaned.modified_count
    return counts

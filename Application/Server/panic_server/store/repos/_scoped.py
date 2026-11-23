"""Shared helpers for the three visibility-scoped collections: catalog_items, endpoint_lists,
dashboards (DATA_MODEL.md §5)."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from panic_common.visibility import VisibilitySpec
from panic_server.store.filters import visibility_filter


def count_owned_by(db: Database[dict[str, Any]], collection: str, username: str) -> int:
    """How many documents in ``collection`` list ``username`` among their ``owner_usernames``
    (``GET /api/v1/users/{id}``'s ``owned_counts``). Regardless of current ``scope`` --
    a resource keeps its creator/owner history even if later re-scoped."""
    return db[collection].count_documents({"owner_usernames": username})


def find_visible(
    db: Database[dict[str, Any]],
    collection: str,
    spec: VisibilitySpec,
    *,
    sort: list[tuple[str, int]] | None = None,
    extra_filter: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    query = visibility_filter(spec)
    if extra_filter:
        query = {"$and": [query, extra_filter]}
    cursor = db[collection].find(query)
    if sort:
        cursor = cursor.sort(sort)
    return list(cursor)

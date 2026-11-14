"""``dashboards`` repository (DATA_MODEL.md §4.7). Widgets are embedded (bounded at 100 by the
API layer, not re-checked here)."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from panic_common.models import Dashboard
from panic_common.visibility import VisibilitySpec
from panic_server.store.cas import (
    base_kwargs,
    cas_update,
    delete_versioned,
    get_or_404,
    insert_versioned,
    new_id,
    utcnow,
)
from panic_server.store.repos._scoped import find_visible

COLLECTION = "dashboards"


def _to_model(doc: dict[str, Any]) -> Dashboard:
    kwargs = base_kwargs(doc)
    # Stored widgets carry no ``dashboard_id`` (DATA_MODEL.md §4.7: "dropped (implicit)"), but
    # panic_common.models.DashboardWidget still requires it -- supply it from the parent doc.
    kwargs["widgets"] = [{**w, "dashboard_id": kwargs["id"]} for w in kwargs.get("widgets") or []]
    return Dashboard(**kwargs)


def create_dashboard(
    db: Database[dict[str, Any]],
    *,
    title: str,
    created_by: str,
    description: str = "",
    scope: str = "GLOBAL",
    team_ids: list[str] | None = None,
    owner_usernames: list[str] | None = None,
    always_display: bool = False,
    sort_order: int = 0,
    widgets: list[dict[str, Any]] | None = None,
    search_keys: list[str] | None = None,
    orphaned: bool = False,
) -> Dashboard:
    now = utcnow()
    doc: dict[str, Any] = {
        "_id": new_id(),
        "title": title,
        "description": description,
        "scope": scope,
        "team_ids": team_ids or [],
        "owner_usernames": owner_usernames or [],
        "always_display": always_display,
        "sort_order": sort_order,
        "widgets": widgets or [],
        "search_keys": search_keys or [],
        "orphaned": orphaned,
        "created_by": created_by,
        "created_at": now,
        "updated_by": created_by,
        "updated_at": now,
        "version": 1,
    }
    return _to_model(insert_versioned(db[COLLECTION], doc))


def get_dashboard(db: Database[dict[str, Any]], dashboard_id: str) -> Dashboard:
    return _to_model(get_or_404(db[COLLECTION], dashboard_id))


def list_visible_dashboards(
    db: Database[dict[str, Any]],
    spec: VisibilitySpec,
    *,
    extra_filter: dict[str, Any] | None = None,
) -> list[Dashboard]:
    docs = find_visible(db, COLLECTION, spec, sort=[("scope", 1), ("sort_order", 1)], extra_filter=extra_filter)
    return [_to_model(d) for d in docs]


def update_dashboard(
    db: Database[dict[str, Any]],
    dashboard_id: str,
    expected_version: int,
    *,
    updated_by: str,
    **fields: Any,
) -> Dashboard:
    fields["updated_at"] = utcnow()
    fields["updated_by"] = updated_by
    doc = cas_update(db[COLLECTION], dashboard_id, expected_version, {"$set": fields, "$inc": {"version": 1}})
    return _to_model(doc)


def delete_dashboard(db: Database[dict[str, Any]], dashboard_id: str, expected_version: int) -> None:
    delete_versioned(db[COLLECTION], dashboard_id, expected_version)

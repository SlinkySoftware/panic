"""``GET /api/v1/ui/dashboards/{id}`` composition (API.md §4.2). Read-only: T-S6-07 owns the
write-side dashboards service (create/update/layout/delete) separately.

Keeps the Mongo round-trip budget (API.md §8: typical/largest both ≤ 6) by batch-fetching every
referenced list and catalog item in one query each (``get_lists_by_ids``/``get_catalog_items_by_ids``)
rather than one query per id.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings as django_settings

from panic_common.models import CatalogItem, Dashboard, EndpointList, UnreachablePolicy, WidgetType
from panic_common.visibility import can_edit, matches, visibility_spec
from panic_server.context import RequestContext
from panic_server.services.launch import build_item_view
from panic_server.store.errors import NotFound
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import zones as zones_repo


def _widget_refs(dashboard: Dashboard) -> tuple[set[str], set[str]]:
    item_ids: set[str] = set()
    list_ids: set[str] = set()
    for w in dashboard.widgets:
        if w.widget_type == WidgetType.HOST and w.catalog_item_id:
            item_ids.add(w.catalog_item_id)
        elif w.widget_type == WidgetType.LIST and w.list_id:
            list_ids.add(w.list_id)
    return item_ids, list_ids


def build_dashboard_view(db: Any, context: RequestContext, dashboard_id: str) -> dict[str, Any]:
    """Build the whole ``/ui/dashboards/{id}`` payload, or raise :class:`NotFound` (AR-2.7: an
    invisible dashboard is ``404``, identical to one that does not exist)."""
    effective = context.effective_user
    assert effective is not None  # the view's IsAuthenticated permission already guarantees this
    spec = visibility_spec(effective)

    dashboard = dashboards_repo.get_dashboard(db, dashboard_id)
    if not matches(spec, dashboard):
        raise NotFound(dashboards_repo.COLLECTION, dashboard_id)

    settings_doc = settings_repo.get_system_settings(db)
    is_global_default = bool(settings_doc and settings_doc.default_global_dashboard_id == dashboard.id)
    is_user_default = effective.default_dashboard_id == dashboard.id
    decision = can_edit(effective, dashboard)

    item_ids_wanted, list_ids_wanted = _widget_refs(dashboard)

    lists_found: dict[str, EndpointList] = {
        lst.id: lst for lst in lists_repo.get_lists_by_ids(db, sorted(list_ids_wanted))
    }
    visible_lists = {lid: lst for lid, lst in lists_found.items() if matches(spec, lst)}
    unavailable_lists = sorted(list_ids_wanted - visible_lists.keys())

    max_list_items = django_settings.PANIC_LIST_WIDGET_MAX_ITEMS
    list_shown_ids: dict[str, list[str]] = {}
    all_list_item_ids: set[str] = set()
    for lid, lst in visible_lists.items():
        shown = lst.item_ids[:max_list_items]
        list_shown_ids[lid] = shown
        all_list_item_ids.update(shown)

    needed_item_ids = item_ids_wanted | all_list_item_ids
    items_found: dict[str, CatalogItem] = {
        item.id: item for item in catalog_repo.get_catalog_items_by_ids(db, sorted(needed_item_ids))
    }
    unavailable_items = sorted(
        iid for iid in item_ids_wanted if iid not in items_found or not matches(spec, items_found[iid])
    )

    # A full zone-id -> name lookup is only needed to resolve ItemView.zone_names for items that
    # actually restrict to specific zones; skip the round trip entirely when none do (the common
    # case -- most items are reachable from "All Zones", DATA_MODEL.md §4.5).
    needs_zones = any(item.zone_ids for item in items_found.values())
    zones_by_id = {z.id: z for z in zones_repo.list_zones(db)} if needs_zones else {}
    hide_unreachable = effective.unreachable_policy == UnreachablePolicy.HIDE

    items_by_id: dict[str, dict[str, Any]] = {}
    for iid, item in items_found.items():
        if not matches(spec, item):
            continue
        view = build_item_view(item, caller=effective, active_zone=context.zone, zones_by_id=zones_by_id)
        if hide_unreachable and not view["reachable"]:
            continue
        items_by_id[iid] = view

    lists_by_id: dict[str, dict[str, Any]] = {}
    for lid, lst in visible_lists.items():
        shown = [iid for iid in list_shown_ids[lid] if iid in items_by_id]
        lists_by_id[lid] = {
            "id": lst.id,
            "title": lst.title,
            "scope": str(lst.scope),
            "item_count": len(lst.item_ids),
            "item_ids": shown,
            "truncated": len(lst.item_ids) > max_list_items,
        }

    widgets = [
        {
            "id": w.id,
            "widget_type": str(w.widget_type),
            "title": w.title,
            "grid_x": w.grid_x,
            "grid_y": w.grid_y,
            "grid_w": w.grid_w,
            "grid_h": w.grid_h,
            "catalog_item_id": w.catalog_item_id,
            "list_id": w.list_id,
        }
        for w in dashboard.widgets
    ]

    return {
        "dashboard": {
            "id": dashboard.id,
            "title": dashboard.title,
            "description": dashboard.description,
            "scope": str(dashboard.scope),
            "team_ids": list(dashboard.team_ids),
            "owner_usernames": list(dashboard.owner_usernames),
            "always_display": dashboard.always_display,
            "version": dashboard.version,
            "can_edit": decision.allowed,
            "is_user_default": is_user_default,
            "is_global_default": is_global_default,
        },
        "widgets": widgets,
        "items": items_by_id,
        "lists": lists_by_id,
        "unavailable": {"items": unavailable_items, "lists": unavailable_lists},
    }


__all__ = ["build_dashboard_view"]

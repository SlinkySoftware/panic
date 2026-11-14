"""``GET /api/v1/ui/search`` composition (API.md §4.2).

Matches DATA_MODEL.md §4.10's query-side rule directly as a Mongo query (anchored,
case-insensitive prefix match per token, ``AND`` across tokens) against each collection's
``search_keys`` index -- never an in-Python scan. Visibility is applied by the same
``list_visible_*`` repo calls every other read path uses (their ``extra_filter`` hook already
supports combining with an arbitrary filter via ``$and``).

**Ranking (not specified verbatim in API.md, decided here):** title-prefix match (the whole
title starts with the raw, case-insensitive query string) ranks above a result that only
token-prefix-matched; ties break by type order ``DASHBOARD, ITEM, LIST`` (documented, stable),
then by title. **Subtitle format (also "my call"):** ``"{protocol} · {site} · {Scope}"`` for an
item (matches the API.md example verbatim), ``"Dashboard · {Scope}"`` for a dashboard, and
``"List · {n} items · {Scope}"`` for a list.
"""

from __future__ import annotations

import re
from typing import Any

from panic_common.models import CatalogItem, Dashboard, EndpointList, ScopeType
from panic_common.visibility import visibility_spec
from panic_server.context import RequestContext
from panic_server.services.launch import build_item_view
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import zones as zones_repo

MIN_QUERY_LENGTH = 2
MAX_TOKENS = 8
MAX_TOKEN_LENGTH = 64
DEFAULT_LIMIT = 20
MAX_LIMIT = 20

_TYPE_ORDER = {"DASHBOARD": 0, "ITEM": 1, "LIST": 2}
_SCOPE_LABELS = {ScopeType.GLOBAL: "Global", ScopeType.TEAM: "Team", ScopeType.PERSONAL: "Personal"}


def _tokens(q: str) -> list[str]:
    return [tok[:MAX_TOKEN_LENGTH] for tok in q.split()[:MAX_TOKENS] if tok]


def _search_filter(tokens: list[str]) -> dict[str, Any]:
    """``{"$and": [{"search_keys": {"$regex": "^tok", "$options": "i"}}, ...]}`` -- anchored
    prefix match per token, ANDed, using the multikey ``search_keys`` index."""
    return {"$and": [{"search_keys": {"$regex": f"^{re.escape(tok)}", "$options": "i"}} for tok in tokens]}


def _scope_label(scope: ScopeType) -> str:
    return _SCOPE_LABELS.get(scope, str(scope))


def _title_prefix_rank(title: str, q: str) -> int:
    return 0 if title.lower().startswith(q.lower()) else 1


def run_search(db: Any, context: RequestContext, q: str, limit: int) -> dict[str, Any]:
    """Build the ``/ui/search`` payload. ``q`` shorter than 2 characters -> empty results."""
    effective = context.effective_user
    assert effective is not None  # IsAuthenticated already guarantees this
    query = q.strip()
    limit = max(1, min(limit, MAX_LIMIT))
    if len(query) < MIN_QUERY_LENGTH:
        return {"results": []}

    tokens = _tokens(query)
    if not tokens:
        return {"results": []}

    spec = visibility_spec(effective)
    search_filter = _search_filter(tokens)

    dashboards: list[Dashboard] = dashboards_repo.list_visible_dashboards(db, spec, extra_filter=search_filter)
    items: list[CatalogItem] = catalog_repo.list_visible_catalog_items(db, spec, extra_filter=search_filter)
    lists_: list[EndpointList] = lists_repo.list_visible_lists(db, spec, extra_filter=search_filter)

    candidates: list[tuple[str, Any, str]] = []
    for d in dashboards:
        candidates.append(("DASHBOARD", d, d.title))
    for i in items:
        candidates.append(("ITEM", i, i.title))
    for lst in lists_:
        candidates.append(("LIST", lst, lst.title))

    candidates.sort(key=lambda c: (_title_prefix_rank(c[2], query), _TYPE_ORDER[c[0]], c[2].lower()))
    candidates = candidates[:limit]

    # Same round-trip-avoidance as dashboards_read.build_dashboard_view: only fetch the full
    # zone set when at least one surviving ITEM result actually restricts to specific zones.
    needs_zones = any(c[0] == "ITEM" and c[1].zone_ids for c in candidates)
    zones_by_id = {z.id: z for z in zones_repo.list_zones(db)} if needs_zones else {}

    results: list[dict[str, Any]] = []
    for kind, obj, title in candidates:
        if kind == "DASHBOARD":
            subtitle = f"Dashboard · {_scope_label(obj.scope)}"
            results.append({"type": kind, "id": obj.id, "title": title, "subtitle": subtitle, "item": None})
        elif kind == "ITEM":
            subtitle = f"{obj.protocol} · {obj.site} · {_scope_label(obj.scope)}"
            item_view = build_item_view(obj, caller=effective, active_zone=context.zone, zones_by_id=zones_by_id)
            results.append({"type": kind, "id": obj.id, "title": title, "subtitle": subtitle, "item": item_view})
        else:
            subtitle = f"List · {len(obj.item_ids)} items · {_scope_label(obj.scope)}"
            results.append({"type": kind, "id": obj.id, "title": title, "subtitle": subtitle, "item": None})

    return {"results": results}


__all__ = ["run_search"]

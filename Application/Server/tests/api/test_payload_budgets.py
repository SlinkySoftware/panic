"""Payload size and Mongo round-trip budgets against the ``loadtest`` reference dataset
(API.md §8): 5,000 catalog items, 50 users, 12 teams, 20 zones, 200 lists, 60 dashboards.

**Round-trip counting method (our call):** two separate measurements per endpoint, for two
separate reasons:

- **Bytes** are measured on the real HTTP response (``django.test.Client``) -- the actual wire
  bytes DRF's ``JSONRenderer`` produces, not an approximation.
- **Round trips** are measured around a *direct call to the ``panic_server.services`` function*
  (e.g. ``build_dashboard_view(db, context, id)``), not the full HTTP request. Every authenticated
  request pays a fixed, endpoint-independent Mongo cost before a view even runs -- the custom
  Mongo-backed session store loading the session (``store.sessions``) and
  ``RequestContextMiddleware`` resolving the real user and the client's Security Zone
  (``panic_server.context``) -- identical on every route, not
  something the endpoint's service composition controls. API.md §8's budget is about *this
  endpoint's own* Mongo cost, so that fixed overhead is deliberately excluded; round-trips is
  the metric to catch an accidental N+1 in *our* code, not to re-measure that fixed cost.
- Either way, the counter is a ``pymongo.monitoring.CommandListener`` attached to a *freshly
  constructed* ``MongoClient`` that temporarily replaces ``panic_server.store.client``'s
  module-level singleton: pymongo snapshots the global ``pymongo.monitoring.register()`` listener
  list once, at client-construction time, so registering globally *after* the session-scoped
  ``mongo_db`` fixture's client already exists would silently listen to nothing. This is
  test-only instrumentation (``_count_mongo_roundtrips`` below); production code is untouched.
- "Round trip" = one ``started`` command event, excluding connection handshake/heartbeat chatter
  (``hello``/``ismaster``/``ping``/``endSessions``/``saslStart``/``saslContinue``) pymongo issues
  itself, which no view/service code requested.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.core.management import call_command
from django.test import Client, RequestFactory
from pymongo import MongoClient
from pymongo import monitoring as pymongo_monitoring
from pymongo.database import Database

from panic_common.search_keys import search_keys
from panic_server.context import SESSION_USER_KEY, RequestContext, build_request_context
from panic_server.services.bootstrap import build_bootstrap
from panic_server.services.dashboards_read import build_dashboard_view
from panic_server.services.search import run_search
from panic_server.store import client as store_client
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import users as users_repo

pytestmark = [pytest.mark.mongo]

_HANDSHAKE_COMMANDS = frozenset({"hello", "ismaster", "ping", "endSessions", "saslStart", "saslContinue"})

# API.md §8 (uncompressed JSON; measured on the DRF Response body, before panic-web's gzip).
BOOTSTRAP_MAX_BYTES = 8 * 1024
BOOTSTRAP_MAX_ROUNDTRIPS = 5
DASHBOARD_TYPICAL_MAX_BYTES = 64 * 1024
DASHBOARD_TYPICAL_MAX_ROUNDTRIPS = 6
DASHBOARD_LARGEST_MAX_BYTES = 256 * 1024
DASHBOARD_LARGEST_MAX_ROUNDTRIPS = 6
SEARCH_MAX_BYTES = 16 * 1024
SEARCH_MAX_ROUNDTRIPS = 4


class _RoundTripCounter(pymongo_monitoring.CommandListener):
    def __init__(self) -> None:
        self.commands: list[str] = []

    def started(self, event: Any) -> None:
        if event.command_name not in _HANDSHAKE_COMMANDS:
            self.commands.append(f"{event.command_name}:{event.database_name}")

    def succeeded(self, event: Any) -> None:
        pass

    def failed(self, event: Any) -> None:
        pass

    @property
    def count(self) -> int:
        return len(self.commands)


@contextmanager
def _count_mongo_roundtrips() -> Iterator[tuple[_RoundTripCounter, Database]]:
    """Yields ``(counter, db)`` -- call the service under test with ``db``, not ``mongo_db``."""
    counter = _RoundTripCounter()
    store_client.reset_client()
    uri = django_settings.PANIC_MONGO_URI
    scoped_client: MongoClient[dict[str, Any]] = MongoClient(
        uri, event_listeners=[counter], tz_aware=True, appname="panic-server-test-roundtrips"
    )
    store_client._client = scoped_client
    try:
        yield counter, store_client.get_db()
    finally:
        scoped_client.close()
        store_client.reset_client()


def _client_as(user_id: str) -> Client:
    client = Client()
    session = client.session
    session[SESSION_USER_KEY] = user_id
    session.save()
    client.cookies[django_settings.SESSION_COOKIE_NAME] = session.session_key
    return client


def _context_for(user_id: str) -> RequestContext:
    """A real :class:`RequestContext` for ``user_id`` (effective == real, no View As), built the
    same way a request would, but outside the counted block -- see module docstring."""
    request = RequestFactory().get("/", REMOTE_ADDR="127.0.0.1")
    request.session = {SESSION_USER_KEY: user_id}  # type: ignore[assignment]
    return build_request_context(request)


@pytest.fixture(scope="module")
def loadtest_db(mongo_db: Database) -> Database:
    """Seed the ``loadtest`` reference dataset once per module (it is sizeable)."""
    call_command("panic_seed", "--profile", "loadtest", "--reset", stdout=io.StringIO())
    return mongo_db


@pytest.fixture(scope="module")
def plain_user_id(loadtest_db: Database) -> str:
    user = users_repo.get_user_by_username(loadtest_db, "loaduser006")  # permissions=[] (see fixtures/loadtest.py)
    assert user is not None
    return user.id


@pytest.fixture(scope="module")
def admin_user_id(loadtest_db: Database) -> str:
    """A fresh ``GLOBAL_ADMIN`` (the mutation budget tests need ``CAN_ADD_GLOBAL`` rights
    to edit the loadtest dataset's ``GLOBAL``-scope dashboards/catalog items/lists; ``plain_user_id``
    deliberately has no permissions, API.md §4.7's read-side budgets only)."""
    user = users_repo.create_user(
        loadtest_db,
        username="budget-admin",
        display_name="Budget Admin",
        default_remote_user="budget-admin",
        permissions=["GLOBAL_ADMIN"],
    )
    return user.id


@pytest.fixture(scope="module")
def typical_dashboard_id(loadtest_db: Database) -> str:
    # Every loadtest dashboard has exactly 3 widgets (fixtures/loadtest.py) -- well inside the
    # "typical" band (<=12 widgets, <=150 items). GLOBAL, so visible to any user.
    dashboards = [d for d in dashboards_repo.list_all_dashboards(loadtest_db) if d.scope == "GLOBAL"]
    return dashboards[0].id


@pytest.fixture(scope="module")
def largest_dashboard_id(loadtest_db: Database) -> str:
    """A dashboard built directly (not from fixtures/loadtest.py, which only ever generates
    3-widget dashboards) to actually exercise API.md §8's "largest" shape: ~30 widgets, 12 lists
    each at the 200-item LIST widget cap, hundreds of distinct items overall."""
    item_ids = [i.id for i in catalog_repo.list_all_catalog_items(loadtest_db) if i.scope == "GLOBAL"]
    assert len(item_ids) >= 3000
    # A fixed, bounded pool of ~500 distinct items, reused (rotated) across all 12 lists -- API.md
    # §8 describes the reference "largest" dashboard as "~600 distinct items" overall, not
    # thousands; reusing a bounded pool is what keeps it there instead of ballooning to 12*250.
    base_pool = item_ids[:500]

    list_ids = []
    for n in range(12):
        # 250 > PANIC_LIST_WIDGET_MAX_ITEMS (200 default): exercises the "truncated" cap too.
        ids = [base_pool[(n * 37 + k) % len(base_pool)] for k in range(250)]
        lst = lists_repo.create_list(loadtest_db, title=f"Budget Test List {n}", created_by="system", item_ids=ids)
        list_ids.append(lst.id)

    host_item_ids = item_ids[3000 - 18 : 3000]  # 18 more items, outside base_pool

    widgets: list[dict[str, Any]] = [
        {"id": f"bt-list-{n}", "widget_type": "LIST", "list_id": lid} for n, lid in enumerate(list_ids)
    ]
    widgets += [
        {"id": f"bt-host-{n}", "widget_type": "HOST", "catalog_item_id": iid} for n, iid in enumerate(host_item_ids)
    ]

    dashboard = dashboards_repo.create_dashboard(
        loadtest_db, title="Budget Test Largest Dashboard", created_by="system", widgets=widgets
    )
    return dashboard.id


@pytest.fixture(scope="module")
def searchable_fixture(loadtest_db: Database) -> None:
    """``fixtures/loadtest.py`` never populates ``search_keys``, so
    none of its 5,000+ catalog items/lists/dashboards are findable -- a handful of real,
    search_keys-bearing documents across all three collections are added here so the search
    budget test exercises an actual, non-empty, multi-type result set."""
    token = "budgetsearch"
    for n in range(25):
        catalog_repo.create_catalog_item(
            loadtest_db,
            title=f"Budgetsearch Item {n:02d}",
            protocol="SSH",
            host=f"budgetsearch-{n:02d}.example.com",
            port=22,
            normalized_key=f"budgetsearch://host{n:02d}",
            created_by="system",
            search_keys=search_keys(f"Budgetsearch Item {n:02d}", f"budgetsearch-{n:02d}.example.com"),
        )
    lists_repo.create_list(
        loadtest_db, title="Budgetsearch List", created_by="system", search_keys=search_keys("Budgetsearch List")
    )
    dashboards_repo.create_dashboard(
        loadtest_db,
        title="Budgetsearch Dashboard",
        created_by="system",
        search_keys=search_keys("Budgetsearch Dashboard"),
    )
    assert token in search_keys("Budgetsearch List")


def test_bootstrap_payload_budget(plain_user_id: str) -> None:
    resp = _client_as(plain_user_id).get("/api/v1/ui/bootstrap")
    assert resp.status_code == 200
    assert len(resp.content) <= BOOTSTRAP_MAX_BYTES, f"bootstrap body {len(resp.content)}B > {BOOTSTRAP_MAX_BYTES}B"

    context = _context_for(plain_user_id)
    with _count_mongo_roundtrips() as (counter, db):
        build_bootstrap(db, context)
    assert counter.count <= BOOTSTRAP_MAX_ROUNDTRIPS, f"bootstrap took {counter.commands}"


def test_dashboard_typical_payload_budget(plain_user_id: str, typical_dashboard_id: str) -> None:
    resp = _client_as(plain_user_id).get(f"/api/v1/ui/dashboards/{typical_dashboard_id}")
    assert resp.status_code == 200
    assert len(resp.content) <= DASHBOARD_TYPICAL_MAX_BYTES

    context = _context_for(plain_user_id)
    with _count_mongo_roundtrips() as (counter, db):
        build_dashboard_view(db, context, typical_dashboard_id)
    assert counter.count <= DASHBOARD_TYPICAL_MAX_ROUNDTRIPS, f"typical dashboard took {counter.commands}"


def test_dashboard_largest_payload_budget(plain_user_id: str, largest_dashboard_id: str) -> None:
    resp = _client_as(plain_user_id).get(f"/api/v1/ui/dashboards/{largest_dashboard_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) > 0
    assert any(lst["truncated"] for lst in body["lists"].values())
    assert len(resp.content) <= DASHBOARD_LARGEST_MAX_BYTES, f"largest dashboard body {len(resp.content)}B"

    context = _context_for(plain_user_id)
    with _count_mongo_roundtrips() as (counter, db):
        build_dashboard_view(db, context, largest_dashboard_id)
    assert counter.count <= DASHBOARD_LARGEST_MAX_ROUNDTRIPS, f"largest dashboard took {counter.commands}"


def test_dashboard_304_has_empty_body(plain_user_id: str, typical_dashboard_id: str) -> None:
    client = _client_as(plain_user_id)
    first = client.get(f"/api/v1/ui/dashboards/{typical_dashboard_id}")
    second = client.get(f"/api/v1/ui/dashboards/{typical_dashboard_id}", HTTP_IF_NONE_MATCH=first["ETag"])
    assert second.status_code == 304
    assert len(second.content) == 0
    # A 304 still fully rebuilds the body to hash it: same round-trip budget as the 200 case,
    # already covered by test_dashboard_typical_payload_budget above.


@pytest.mark.usefixtures("searchable_fixture")
def test_search_payload_budget(plain_user_id: str) -> None:
    resp = _client_as(plain_user_id).get("/api/v1/ui/search?q=budgetsearch")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) > 0
    assert {r["type"] for r in body["results"]} >= {"ITEM"}  # at least items matched; see fixture
    assert len(resp.content) <= SEARCH_MAX_BYTES, f"search body {len(resp.content)}B > {SEARCH_MAX_BYTES}B"

    context = _context_for(plain_user_id)
    with _count_mongo_roundtrips() as (counter, db):
        run_search(db, context, "budgetsearch", 20)
    assert counter.count <= SEARCH_MAX_ROUNDTRIPS, f"search took {counter.commands}"


# ---------------------------------------------------------------- mutation budgets
#
# API.md §8: "Any mutation response <= 32 KB (dashboard layout <= 48 KB)". These extend this same
# file/pattern (not a parallel one) for the write endpoints, reusing the loadtest
# dataset's catalog items so the dashboard-layout case is a realistic, non-trivial payload (close
# to the 100-widget cap), not a one-widget toy.

MUTATION_MAX_BYTES = 32 * 1024
DASHBOARD_LAYOUT_MUTATION_MAX_BYTES = 48 * 1024


def test_dashboard_layout_mutation_payload_budget(loadtest_db: Database, admin_user_id: str) -> None:
    item_ids = [i.id for i in catalog_repo.list_all_catalog_items(loadtest_db) if i.scope == "GLOBAL"][:100]
    dashboard = dashboards_repo.create_dashboard(loadtest_db, title="Mutation Budget Dashboard", created_by="system")
    widgets = [
        {
            "widget_type": "HOST",
            "catalog_item_id": iid,
            "grid_x": (n % 3) * 4 + 1,
            "grid_y": n // 3 + 1,
            "grid_w": 4,
            "grid_h": 1,
        }
        for n, iid in enumerate(item_ids)
    ]
    resp = _client_as(admin_user_id).put(
        f"/api/v1/dashboards/{dashboard.id}/layout",
        data=json.dumps({"widgets": widgets}),
        content_type="application/json",
        HTTP_IF_MATCH=str(dashboard.version),
    )
    assert resp.status_code == 200, resp.content
    assert len(resp.json()["widgets"]) == len(item_ids)
    assert len(resp.content) <= DASHBOARD_LAYOUT_MUTATION_MAX_BYTES, f"layout mutation body {len(resp.content)}B"


def test_catalog_mutation_payload_budget(loadtest_db: Database, admin_user_id: str) -> None:
    item = next(i for i in catalog_repo.list_all_catalog_items(loadtest_db) if i.scope == "GLOBAL")
    resp = _client_as(admin_user_id).patch(
        f"/api/v1/catalog/{item.id}", data=json.dumps({"description": "budget check"}), content_type="application/json"
    )
    assert resp.status_code == 200, resp.content
    assert len(resp.content) <= MUTATION_MAX_BYTES, f"catalog mutation body {len(resp.content)}B"


def test_list_mutation_payload_budget(loadtest_db: Database, admin_user_id: str) -> None:
    item_ids = [i.id for i in catalog_repo.list_all_catalog_items(loadtest_db) if i.scope == "GLOBAL"][:50]
    lst = lists_repo.create_list(loadtest_db, title="Mutation Budget List", created_by="system", item_ids=item_ids)
    resp = _client_as(admin_user_id).put(
        f"/api/v1/lists/{lst.id}",
        data=json.dumps({"title": "Mutation Budget List", "scope": "GLOBAL", "item_ids": list(reversed(item_ids))}),
        content_type="application/json",
        HTTP_IF_MATCH=str(lst.version),
    )
    assert resp.status_code == 200, resp.content
    assert len(resp.content) <= MUTATION_MAX_BYTES, f"list mutation body {len(resp.content)}B"

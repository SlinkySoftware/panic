"""Unit tests for the relational persistence layer (models, DatabasePortalStore, panic_seed)."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from panic_common.models import (
    CatalogItem,
    DashboardWidget,
    EndpointList,
    PermissionFlag,
    Protocol,
    ScopeType,
    SiteDefinition,
    UserAccount,
    WidgetType,
)
from panic_common.rbac import validate_list_item_scopes
from panic_server.models import (
    AuditLogRecord,
    CatalogItemRecord,
    DashboardRecord,
    DashboardWidgetRecord,
    SiteRecord,
    UserAccountRecord,
)
from panic_server.state import MockPortalStore
from panic_server.store_db import (
    DASH_GLOBAL_NETOPS_ID,
    DASH_GLOBAL_NOC_ID,
    DASH_PERSONAL_BENCH_ID,
    DASH_TEAM_COMPUTE_ID,
    DatabasePortalStore,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def store() -> DatabasePortalStore:
    s = DatabasePortalStore()
    s.reset()
    return s


def test_model_round_trip_preserves_domain_contract() -> None:
    fx = MockPortalStore()
    for item in fx.catalog:
        rec = CatalogItemRecord.from_domain(item)
        rec.save()
        assert CatalogItemRecord.objects.get(pk=item.id).to_domain() == item
    for user in fx.users:
        UserAccountRecord.from_domain(user).save()
        assert UserAccountRecord.objects.get(pk=user.id).to_domain() == user
    dash = fx.dashboards[0]
    DashboardRecord.from_domain(dash).save()
    for i, w in enumerate(dash.widgets):
        DashboardWidgetRecord.from_domain(w, sort_order=i).save()
    assert DashboardRecord.objects.get(pk=dash.id).to_domain() == dash


def test_site_code_is_unique() -> None:
    from django.db import IntegrityError, transaction

    SiteRecord.from_domain(SiteDefinition(id="s1", code="9TST", name="Test")).save()
    with pytest.raises(IntegrityError), transaction.atomic():
        SiteRecord.from_domain(SiteDefinition(id="s2", code="9TST", name="Dup")).save()


def test_reset_seeds_canonical_fixtures(store: DatabasePortalStore) -> None:
    assert {s.code for s in store.sites} == {"2SYA", "3MEL", "4BNE", "1CBR"}
    assert {d.id for d in store.dashboards} >= {DASH_GLOBAL_NETOPS_ID, DASH_TEAM_COMPUTE_ID}
    assert store.system_settings.default_global_dashboard_id == DASH_GLOBAL_NETOPS_ID
    assert store.auth_user.username == "joperator"
    snap = store.build_snapshot()
    assert snap["user"]["effective_default_dashboard_id"] == DASH_GLOBAL_NETOPS_ID


def test_persist_writes_only_changes_and_survives_reload(store: DatabasePortalStore) -> None:
    assert store.persist() == {"upserted": 0, "deleted": 0}
    store.sites[0].name = "Renamed Core DC"
    store.catalog = [c for c in store.catalog if c.id != "cat-web-ipam"]
    stats = store.persist()
    assert stats == {"upserted": 1, "deleted": 1}

    other = DatabasePortalStore()
    other.refresh()
    assert next(s for s in other.sites if s.id == store.sites[0].id).name == "Renamed Core DC"
    assert all(c.id != "cat-web-ipam" for c in other.catalog)


def test_catalog_crud_and_list_cleanup(store: DatabasePortalStore) -> None:
    item = CatalogItem(
        id="cat-test-1",
        title="Test Switch",
        protocol=Protocol.SSH,
        host="sw1.lab.example.com",
        port=22,
        normalized_key="ssh://sw1.lab.example.com:22",
        scope=ScopeType.GLOBAL,
    )
    store.save_catalog_item(item)
    assert CatalogItemRecord.objects.filter(pk="cat-test-1").exists()
    item.title = "Test Switch (edited)"
    store.save_catalog_item(item)
    assert CatalogItemRecord.objects.get(pk="cat-test-1").title == "Test Switch (edited)"

    assert store.delete_catalog_item("cat-rtr-2sya-01")
    store.refresh()
    routers = next(lst for lst in store.lists if lst.id == "list-global-routers")
    assert "cat-rtr-2sya-01" not in routers.item_ids


def test_same_scope_list_validation_against_db_catalog(store: DatabasePortalStore) -> None:
    ok, _ = validate_list_item_scopes(ScopeType.GLOBAL, ["cat-rtr-2sya-01"], store.catalog)
    assert ok
    bad, errors = validate_list_item_scopes(ScopeType.GLOBAL, ["cat-pers-lab-rtr"], store.catalog)
    assert not bad and errors
    store.save_list(
        EndpointList(id="list-x", title="X", scope=ScopeType.GLOBAL, item_ids=["cat-rtr-3mel-02", "cat-rtr-2sya-01"])
    )
    store.refresh()
    assert next(lst for lst in store.lists if lst.id == "list-x").item_ids == ["cat-rtr-3mel-02", "cat-rtr-2sya-01"]


def test_widget_layout_persistence_and_ordering(store: DatabasePortalStore) -> None:
    dash = next(d for d in store.dashboards if d.id == DASH_GLOBAL_NOC_ID)
    dash.widgets = [
        DashboardWidget(id="w-b", dashboard_id=dash.id, widget_type=WidgetType.LIST, grid_w=12, list_id="list-x"),
        DashboardWidget(id="w-a", dashboard_id=dash.id, widget_type=WidgetType.HOST, grid_x=5, grid_w=6, grid_h=3),
    ]
    store.save_dashboard(dash)
    # Same widget id reused on a different dashboard must not collide.
    other = next(d for d in store.dashboards if d.id == DASH_TEAM_COMPUTE_ID)
    other.widgets = [DashboardWidget(id="w-a", dashboard_id=other.id, widget_type=WidgetType.HOST)]
    store.save_dashboard(other)

    store.refresh()
    reloaded = next(d for d in store.dashboards if d.id == DASH_GLOBAL_NOC_ID)
    assert [w.id for w in reloaded.widgets] == ["w-b", "w-a"]
    assert (reloaded.widgets[1].grid_x, reloaded.widgets[1].grid_w, reloaded.widgets[1].grid_h) == (5, 6, 3)

    store.delete_dashboard(DASH_GLOBAL_NOC_ID)
    assert not DashboardWidgetRecord.objects.filter(dashboard_id=DASH_GLOBAL_NOC_ID).exists()


def test_default_dashboard_precedence(store: DatabasePortalStore) -> None:
    admin = store.get_user_by_username("joperator")
    assert admin is not None
    assert store.resolve_default_dashboard(admin)[1] == "SYSTEM_GLOBAL"
    admin.default_dashboard_id = DASH_PERSONAL_BENCH_ID
    store.save_user(admin)
    store.refresh()
    admin = store.get_user_by_username("joperator")
    assert admin is not None
    dash, source = store.resolve_default_dashboard(admin)
    assert (dash.id if dash else None, source) == (DASH_PERSONAL_BENCH_ID, "USER")

    # User without team access to the system default falls back to first visible dashboard.
    stranger = UserAccount(id="usr-x", username="nobody", display_name="Nobody", default_remote_user="nobody")
    store.system_settings.default_global_dashboard_id = "missing"
    _, source = store.resolve_default_dashboard(stranger)
    assert source == "FALLBACK"


def test_user_identity_fields_survive_domain_updates(store: DatabasePortalStore) -> None:
    store.set_user_password_hash("alex.chen", "pbkdf2_sha256$fake")
    user = store.get_user_by_username("alex.chen")
    assert user is not None
    user.permissions = [PermissionFlag.CAN_ADD_TEAM]
    store.save_user(user)
    assert store.get_user_password_hash("alex.chen") == "pbkdf2_sha256$fake"
    assert UserAccountRecord.objects.get(username="alex.chen").permissions == ["CAN_ADD_TEAM"]


def test_audit_write_through_and_query(store: DatabasePortalStore) -> None:
    store.record_audit("catalog.create", "catalog_item", "cat-1", "Created alpha")
    store.record_audit("zone.update", "security_zone", "zone-dmz", "Updated beta")
    assert store.audit_logs[0].action == "zone.update"
    assert AuditLogRecord.objects.filter(action="catalog.create", target_id="cat-1").exists()
    assert [e.target_id for e in store.query_audit(action="zone.update")] == ["zone-dmz"]
    assert [e.target_id for e in store.query_audit(q="alpha")] == ["cat-1"]
    assert len(store.query_audit(limit=1)) == 1


def test_panic_seed_is_idempotent() -> None:
    out = StringIO()
    call_command("panic_seed", stdout=out)
    counts = (SiteRecord.objects.count(), CatalogItemRecord.objects.count(), DashboardWidgetRecord.objects.count())
    assert counts[0] == 4
    call_command("panic_seed", stdout=out)
    assert counts == (
        SiteRecord.objects.count(),
        CatalogItemRecord.objects.count(),
        DashboardWidgetRecord.objects.count(),
    )
    call_command("panic_seed", "--if-empty", stdout=out)
    assert "skipping" in out.getvalue()

    SiteRecord.objects.filter(code="1CBR").update(name="Operator Edited")
    call_command("panic_seed", stdout=out)
    assert SiteRecord.objects.get(code="1CBR").name == "Operator Edited"
    call_command("panic_seed", "--reset", stdout=out)
    assert SiteRecord.objects.get(code="1CBR").name == "Canberra Gov DC"

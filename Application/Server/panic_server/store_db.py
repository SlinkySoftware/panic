"""Relational persistence for PANIC (Stage 2): ``DatabasePortalStore``.

``DatabasePortalStore`` keeps the exact public contract of the Stage 1 ``MockPortalStore``
(in-memory ``panic_common`` Pydantic models, ``build_snapshot()``, ``record_audit()`` ...) but
backs every entity with Django ORM records (SQLite or PostgreSQL).

Lifecycle (driven by ``panic_server.middleware.PortalStoreMiddleware`` per request):

1. ``refresh()`` loads the current relational state into the in-memory working set and records a
   *baseline* fingerprint of every entity.
2. Views read and mutate the working set exactly as in Stage 1.
3. ``persist()`` diffs the working set against the baseline and writes only created, changed, or
   deleted entities inside a single database transaction.

Audit log entries are written straight through to the database by ``record_audit()``.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from django.db import models, transaction
from pydantic import BaseModel

from panic_common.models import (
    AuditLogEntry,
    CatalogItem,
    Dashboard,
    EndpointList,
    SecurityZone,
    SimulationState,
    SiteDefinition,
    SystemSettings,
    TeamDefinition,
    UserAccount,
)
from panic_server.models import (
    AuditLogRecord,
    CatalogItemRecord,
    DashboardRecord,
    DashboardWidgetRecord,
    EndpointListRecord,
    SecurityZoneRecord,
    SiteRecord,
    SystemSettingsRecord,
    TeamRecord,
    UserAccountRecord,
)
from panic_server.state import (
    DASH_GLOBAL_NETOPS_ID,
    DASH_GLOBAL_NOC_ID,
    DASH_LEGACY_ALIASES,
    DASH_PERSONAL_BENCH_ID,
    DASH_TEAM_COMPUTE_ID,
    DASH_TEAM_SECOPS_ID,
    MockPortalStore,
)

__all__ = [
    "DASH_GLOBAL_NETOPS_ID",
    "DASH_GLOBAL_NOC_ID",
    "DASH_LEGACY_ALIASES",
    "DASH_PERSONAL_BENCH_ID",
    "DASH_TEAM_COMPUTE_ID",
    "DASH_TEAM_SECOPS_ID",
    "DatabasePortalStore",
]

AUDIT_WINDOW = 500
SYSTEM_SETTINGS_PK = "default"

# Fields owned by the identity layer (Stage 3) that the domain model does not carry.
_USER_IDENTITY_FIELDS = {"password_hash", "auth_source"}


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_ts() -> str:
    # Microsecond precision keeps audit ordering stable for entries written within the same second.
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _fingerprint(obj: BaseModel) -> str:
    return json.dumps(obj.model_dump(mode="json"), sort_keys=True)


def _record_fields(record: models.Model, exclude: Iterable[str] = ()) -> dict[str, Any]:
    """Return non-PK concrete field values of ``record`` suitable for ``update_or_create(defaults=...)``."""
    skip = set(exclude)
    out: dict[str, Any] = {}
    for field in record._meta.concrete_fields:
        if field.primary_key or field.name in skip:
            continue
        out[field.attname] = getattr(record, field.attname)
    return out


class DatabasePortalStore(MockPortalStore):
    """Django ORM backed portal store preserving the ``MockPortalStore`` public contract."""

    def __init__(self) -> None:
        # Deliberately does not touch the database at import time (migrations may not have run yet).
        self._lock = threading.RLock()
        self._baseline: dict[str, dict[str, str]] = {}
        self._loaded = False
        # Populate an in-memory working set from fixtures so the object is usable before refresh().
        MockPortalStore.reset(self)
        self.audit_logs = []

    # ------------------------------------------------------------------ seeding / reset
    def _fixture_state(self) -> MockPortalStore:
        """Return a fresh in-memory fixture store (canonical seed data)."""
        return MockPortalStore()

    def is_empty(self) -> bool:
        return not (SiteRecord.objects.exists() or UserAccountRecord.objects.exists())

    def wipe(self) -> None:
        with self._lock, transaction.atomic():
            for model in (
                DashboardWidgetRecord,
                DashboardRecord,
                EndpointListRecord,
                CatalogItemRecord,
                SecurityZoneRecord,
                TeamRecord,
                SiteRecord,
                SystemSettingsRecord,
                AuditLogRecord,
            ):
                model.objects.all().delete()
            UserAccountRecord.objects.all().delete()
            self._baseline = {}

    def seed_defaults(self, force: bool = False) -> dict[str, int]:
        """Idempotently insert canonical seed fixtures.

        Existing records (matched by primary key) are left untouched so re-running never duplicates
        or clobbers operator edits. ``force=True`` wipes the database first (factory reset).
        """
        with self._lock, transaction.atomic():
            if force:
                self.wipe()
            fx = self._fixture_state()
            created: dict[str, int] = {}

            def _insert(label: str, model: type[models.Model], records: list[models.Model]) -> None:
                existing = set(model.objects.values_list("pk", flat=True))
                new = [r for r in records if r.pk not in existing]
                model.objects.bulk_create(new)
                created[label] = len(new)

            _insert("sites", SiteRecord, [SiteRecord.from_domain(s) for s in fx.sites])
            _insert("teams", TeamRecord, [TeamRecord.from_domain(t) for t in fx.teams])
            _insert("zones", SecurityZoneRecord, [SecurityZoneRecord.from_domain(z) for z in fx.zones])
            # Users may collide on the unique username with identity-provisioned accounts.
            existing_usernames = set(UserAccountRecord.objects.values_list("username", flat=True))
            _insert(
                "users",
                UserAccountRecord,
                [UserAccountRecord.from_domain(u) for u in fx.users if u.username not in existing_usernames],
            )
            _insert("catalog", CatalogItemRecord, [CatalogItemRecord.from_domain(c) for c in fx.catalog])
            _insert("lists", EndpointListRecord, [EndpointListRecord.from_domain(lst) for lst in fx.lists])
            existing_dash = set(DashboardRecord.objects.values_list("pk", flat=True))
            new_dash = [d for d in fx.dashboards if d.id not in existing_dash]
            DashboardRecord.objects.bulk_create([DashboardRecord.from_domain(d) for d in new_dash])
            DashboardWidgetRecord.objects.bulk_create(
                [
                    DashboardWidgetRecord.from_domain(w, sort_order=idx)
                    for d in new_dash
                    for idx, w in enumerate(d.widgets)
                ]
            )
            created["dashboards"] = len(new_dash)
            if not SystemSettingsRecord.objects.filter(pk=SYSTEM_SETTINGS_PK).exists():
                SystemSettingsRecord.from_domain(fx.system_settings, SYSTEM_SETTINGS_PK).save(force_insert=True)
                created["system_settings"] = 1
            else:
                created["system_settings"] = 0
            _insert("audit_logs", AuditLogRecord, [AuditLogRecord.from_domain(a) for a in fx.audit_logs])
        self._loaded = False
        return created

    def ensure_seeded(self) -> bool:
        """Seed canonical fixtures when the database is empty. Returns True when seeding happened."""
        with self._lock:
            if self.is_empty():
                self.seed_defaults()
                return True
            return False

    def reset(self) -> None:
        """Factory reset: wipe all relational state, re-seed fixtures, and reload (test isolation)."""
        with self._lock:
            self.seed_defaults(force=True)
            self.simulation = SimulationState()
            self.refresh()

    # ------------------------------------------------------------------ load / persist
    def refresh(self) -> None:
        """Load the full relational state into the in-memory working set."""
        with self._lock:
            self.sites = [r.to_domain() for r in SiteRecord.objects.order_by("created_at", "code")]
            self.teams = [r.to_domain() for r in TeamRecord.objects.order_by("created_at", "id")]
            self.zones = [r.to_domain() for r in SecurityZoneRecord.objects.order_by("created_at", "id")]
            self.users = [r.to_domain() for r in UserAccountRecord.objects.order_by("id")]
            self.catalog = [r.to_domain() for r in CatalogItemRecord.objects.order_by("-created_at", "id")]
            self.lists = [r.to_domain() for r in EndpointListRecord.objects.order_by("created_at", "id")]
            widgets_by_dash: dict[str, list[Any]] = {}
            for w in DashboardWidgetRecord.objects.order_by("dashboard_id", "sort_order", "row_id"):
                widgets_by_dash.setdefault(str(w.dashboard_id), []).append(w.to_domain())
            self.dashboards = [
                r.to_domain(widgets=widgets_by_dash.get(r.id, []))
                for r in DashboardRecord.objects.order_by("sort_order", "id")
            ]
            settings_rec = SystemSettingsRecord.objects.filter(pk=SYSTEM_SETTINGS_PK).first()
            self.system_settings = (
                settings_rec.to_domain()
                if settings_rec is not None
                else SystemSettings(
                    default_global_dashboard_id=self.dashboards[0].id if self.dashboards else "",
                    updated_by="system",
                    updated_at=_now_iso(),
                )
            )
            self.audit_logs = [
                r.to_domain() for r in AuditLogRecord.objects.order_by("-created_at", "-pk")[:AUDIT_WINDOW]
            ]
            if self.users and not any(u.id == self.simulation.active_user_id for u in self.users):
                self.simulation.active_user_id = self.users[0].id
                self.simulation.view_as_user_id = None
            self._baseline = self._current_fingerprints()
            self._loaded = True

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    def _collections(self) -> dict[str, list[Any]]:
        return {
            "sites": list(self.sites),
            "teams": list(self.teams),
            "zones": list(self.zones),
            "users": list(self.users),
            "catalog": list(self.catalog),
            "lists": list(self.lists),
            "dashboards": list(self.dashboards),
            "system_settings": [self.system_settings],
        }

    def _current_fingerprints(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for label, objs in self._collections().items():
            if label == "system_settings":
                out[label] = {SYSTEM_SETTINGS_PK: _fingerprint(objs[0])}
            else:
                out[label] = {o.id: _fingerprint(o) for o in objs}
        return out

    def has_pending_changes(self) -> bool:
        with self._lock:
            return self._current_fingerprints() != self._baseline

    def persist(self) -> dict[str, int]:
        """Write created/changed/deleted entities (vs. the last baseline) in one transaction."""
        with self._lock:
            current = self._current_fingerprints()
            stats = {"upserted": 0, "deleted": 0}
            if current == self._baseline:
                return stats
            colls = self._collections()
            with transaction.atomic():
                # Deletions first so unique-key renames (e.g. site codes) never collide.
                for label, model in self._model_map().items():
                    removed = set(self._baseline.get(label, {})) - set(current.get(label, {}))
                    if removed and label != "system_settings":
                        model.objects.filter(pk__in=removed).delete()
                        stats["deleted"] += len(removed)
                for label in self._model_map():
                    before = self._baseline.get(label, {})
                    for obj in colls[label]:
                        key = SYSTEM_SETTINGS_PK if label == "system_settings" else obj.id
                        if before.get(key) == current[label][key]:
                            continue
                        self._upsert(label, obj)
                        stats["upserted"] += 1
            self._baseline = current
            return stats

    @staticmethod
    def _model_map() -> dict[str, type[models.Model]]:
        return {
            "sites": SiteRecord,
            "teams": TeamRecord,
            "zones": SecurityZoneRecord,
            "users": UserAccountRecord,
            "catalog": CatalogItemRecord,
            "lists": EndpointListRecord,
            "dashboards": DashboardRecord,
            "system_settings": SystemSettingsRecord,
        }

    def _upsert(self, label: str, obj: Any) -> None:
        if label == "sites":
            rec: models.Model = SiteRecord.from_domain(obj)
            SiteRecord.objects.update_or_create(pk=rec.pk, defaults=_record_fields(rec))
        elif label == "teams":
            rec = TeamRecord.from_domain(obj)
            TeamRecord.objects.update_or_create(pk=rec.pk, defaults=_record_fields(rec))
        elif label == "zones":
            rec = SecurityZoneRecord.from_domain(obj)
            SecurityZoneRecord.objects.update_or_create(pk=rec.pk, defaults=_record_fields(rec))
        elif label == "users":
            rec = UserAccountRecord.from_domain(obj)
            UserAccountRecord.objects.update_or_create(
                pk=rec.pk, defaults=_record_fields(rec, exclude=_USER_IDENTITY_FIELDS)
            )
        elif label == "catalog":
            rec = CatalogItemRecord.from_domain(obj)
            CatalogItemRecord.objects.update_or_create(pk=rec.pk, defaults=_record_fields(rec))
        elif label == "lists":
            rec = EndpointListRecord.from_domain(obj)
            EndpointListRecord.objects.update_or_create(pk=rec.pk, defaults=_record_fields(rec))
        elif label == "dashboards":
            dash: Dashboard = obj
            rec = DashboardRecord.from_domain(dash)
            DashboardRecord.objects.update_or_create(pk=rec.pk, defaults=_record_fields(rec))
            DashboardWidgetRecord.objects.filter(dashboard_id=dash.id).delete()
            DashboardWidgetRecord.objects.bulk_create(
                [
                    DashboardWidgetRecord.from_domain(w.model_copy(update={"dashboard_id": dash.id}), sort_order=i)
                    for i, w in enumerate(dash.widgets)
                ]
            )
        elif label == "system_settings":
            rec = SystemSettingsRecord.from_domain(obj, SYSTEM_SETTINGS_PK)
            SystemSettingsRecord.objects.update_or_create(pk=SYSTEM_SETTINGS_PK, defaults=_record_fields(rec))

    # ------------------------------------------------------------------ explicit repository API
    def _replace_or_append(self, attr: str, obj: Any, prepend: bool = False) -> None:
        items: list[Any] = getattr(self, attr)
        for idx, existing in enumerate(items):
            if existing.id == obj.id:
                items[idx] = obj
                break
        else:
            if prepend:
                items.insert(0, obj)
            else:
                items.append(obj)

    def _remove(self, attr: str, obj_id: str) -> bool:
        items: list[Any] = getattr(self, attr)
        kept = [i for i in items if i.id != obj_id]
        setattr(self, attr, kept)
        return len(kept) != len(items)

    def save_site(self, site: SiteDefinition) -> SiteDefinition:
        with self._lock:
            self._replace_or_append("sites", site)
            self.persist()
            return site

    def delete_site(self, site_id: str) -> bool:
        with self._lock:
            removed = self._remove("sites", site_id)
            self.persist()
            return removed

    def save_team(self, team: TeamDefinition) -> TeamDefinition:
        with self._lock:
            self._replace_or_append("teams", team)
            self.persist()
            return team

    def delete_team(self, team_id: str) -> bool:
        with self._lock:
            removed = self._remove("teams", team_id)
            self.persist()
            return removed

    def save_zone(self, zone: SecurityZone) -> SecurityZone:
        with self._lock:
            self._replace_or_append("zones", zone)
            self.persist()
            return zone

    def delete_zone(self, zone_id: str) -> bool:
        with self._lock:
            removed = self._remove("zones", zone_id)
            self.persist()
            return removed

    def save_user(self, user: UserAccount) -> UserAccount:
        with self._lock:
            self._replace_or_append("users", user)
            self.persist()
            return user

    def get_user_by_username(self, username: str) -> UserAccount | None:
        with self._lock:
            return next((u for u in self.users if u.username == username), None)

    def set_user_password_hash(self, username: str, password_hash: str, auth_source: str = "local") -> None:
        UserAccountRecord.objects.filter(username=username).update(
            password_hash=password_hash, auth_source=auth_source
        )

    def get_user_password_hash(self, username: str) -> str:
        rec = UserAccountRecord.objects.filter(username=username).only("password_hash").first()
        return rec.password_hash if rec is not None else ""

    def save_system_settings(self, settings_obj: SystemSettings) -> SystemSettings:
        with self._lock:
            self.system_settings = settings_obj
            self.persist()
            return settings_obj

    def save_catalog_item(self, item: CatalogItem) -> CatalogItem:
        with self._lock:
            self._replace_or_append("catalog", item, prepend=True)
            self.persist()
            return item

    def delete_catalog_item(self, item_id: str) -> bool:
        with self._lock:
            removed = self._remove("catalog", item_id)
            for lst in self.lists:
                if item_id in lst.item_ids:
                    lst.item_ids = [i for i in lst.item_ids if i != item_id]
            self.persist()
            return removed

    def save_list(self, endpoint_list: EndpointList) -> EndpointList:
        with self._lock:
            self._replace_or_append("lists", endpoint_list)
            self.persist()
            return endpoint_list

    def delete_list(self, list_id: str) -> bool:
        with self._lock:
            removed = self._remove("lists", list_id)
            self.persist()
            return removed

    def save_dashboard(self, dashboard: Dashboard) -> Dashboard:
        with self._lock:
            self._replace_or_append("dashboards", dashboard)
            self.persist()
            return dashboard

    def delete_dashboard(self, dashboard_id: str) -> bool:
        with self._lock:
            removed = self._remove("dashboards", dashboard_id)
            self.persist()
            return removed

    # ------------------------------------------------------------------ audit (write-through)
    def record_audit(
        self,
        action: str,
        target_type: str,
        target_id: str,
        summary: str,
        details: dict[str, Any] | None = None,
        actor_username: str | None = None,
    ) -> AuditLogEntry:
        with self._lock:
            if actor_username is None:
                actor_username = self.active_user.username if self.users else "system"
            entry = AuditLogEntry(
                id=f"aud-{uuid.uuid4().hex[:12]}",
                actor_username=actor_username,
                action=action,
                target_type=target_type,
                target_id=target_id,
                summary=summary,
                details=details or {},
                created_at=_audit_ts(),
            )
            AuditLogRecord.from_domain(entry).save(force_insert=True)
            self.audit_logs.insert(0, entry)
            del self.audit_logs[AUDIT_WINDOW:]
            return entry

    def query_audit(
        self,
        *,
        actor: str = "",
        action: str = "",
        target_type: str = "",
        q: str = "",
        limit: int = 100,
    ) -> list[AuditLogEntry]:
        """Filter persisted audit entries (newest first)."""
        qs = AuditLogRecord.objects.all()
        if actor:
            qs = qs.filter(actor_username__iexact=actor)
        if action:
            qs = qs.filter(action__istartswith=action)
        if target_type:
            qs = qs.filter(target_type__iexact=target_type)
        if q:
            qs = qs.filter(
                models.Q(summary__icontains=q) | models.Q(target_id__icontains=q) | models.Q(action__icontains=q)
            )
        limit = max(1, min(int(limit), 1000))
        return [r.to_domain() for r in qs.order_by("-created_at", "-pk")[:limit]]

    def database_ok(self) -> bool:
        try:
            SystemSettingsRecord.objects.exists()
        except Exception:
            return False
        return True

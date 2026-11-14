"""Django ORM persistence models for PANIC Stage 2 (SQLite & PostgreSQL)."""

from __future__ import annotations

from typing import Any

from django.db import models

from panic_common.models import (
    AuditLogEntry,
    CatalogItem,
    Dashboard,
    DashboardWidget,
    DensityMode,
    EndpointList,
    PermissionFlag,
    Protocol,
    ScopeType,
    SecurityZone,
    SiteDefinition,
    SystemSettings,
    TeamDefinition,
    ThemeMode,
    UnreachablePolicy,
    UserAccount,
    WidgetType,
)


def _default_list() -> list[Any]:
    return []


def _default_dict() -> dict[str, Any]:
    return {}


class SiteRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    code = models.CharField(max_length=32, unique=True, db_index=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    created_at = models.CharField(max_length=64, default="2026-11-01T00:00:00Z")

    class Meta:
        db_table = "panic_site"
        ordering = ["id"]

    def to_domain(self) -> SiteDefinition:
        return SiteDefinition(
            id=self.id,
            code=self.code,
            name=self.name,
            description=self.description,
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, domain: SiteDefinition) -> SiteRecord:
        return cls(
            id=domain.id,
            code=domain.code,
            name=domain.name,
            description=domain.description,
            created_at=domain.created_at,
        )


class TeamRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    members = models.JSONField(default=_default_list, blank=True)
    created_at = models.CharField(max_length=64, default="2026-11-01T00:00:00Z")

    class Meta:
        db_table = "panic_team"
        ordering = ["id"]

    def to_domain(self) -> TeamDefinition:
        return TeamDefinition(
            id=self.id,
            code=self.code,
            name=self.name,
            description=self.description,
            members=[str(m) for m in (self.members or [])],
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, domain: TeamDefinition) -> TeamRecord:
        return cls(
            id=domain.id,
            code=domain.code,
            name=domain.name,
            description=domain.description,
            members=list(domain.members),
            created_at=domain.created_at,
        )


class SecurityZoneRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    priority = models.IntegerField(default=100, db_index=True)
    cidrs = models.JSONField(default=_default_list, blank=True)
    created_at = models.CharField(max_length=64, default="2026-11-01T00:00:00Z")

    class Meta:
        db_table = "panic_security_zone"
        ordering = ["-priority", "id"]

    def to_domain(self) -> SecurityZone:
        return SecurityZone(
            id=self.id,
            name=self.name,
            description=self.description,
            priority=int(self.priority),
            cidrs=[str(c) for c in (self.cidrs or [])],
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, domain: SecurityZone) -> SecurityZoneRecord:
        return cls(
            id=domain.id,
            name=domain.name,
            description=domain.description,
            priority=int(domain.priority),
            cidrs=list(domain.cidrs),
            created_at=domain.created_at,
        )


class UserAccountRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    username = models.CharField(max_length=128, unique=True, db_index=True)
    display_name = models.CharField(max_length=255)
    default_remote_user = models.CharField(max_length=128)
    ssh_template = models.CharField(max_length=512, default="ssh {user}@{host} -p {port} {flags}")
    password_hash = models.CharField(max_length=255, blank=True, default="")
    auth_source = models.CharField(max_length=64, default="local")
    permissions = models.JSONField(default=_default_list, blank=True)
    team_ids = models.JSONField(default=_default_list, blank=True)
    pinned_dashboard_ids = models.JSONField(default=_default_list, blank=True)
    default_dashboard_id = models.CharField(max_length=64, null=True, blank=True)
    density = models.CharField(max_length=32, default="COMFORT")
    theme = models.CharField(max_length=32, default="DARK")
    unreachable_policy = models.CharField(max_length=32, default="DIM")

    class Meta:
        db_table = "panic_user_account"
        ordering = ["id"]

    def to_domain(self) -> UserAccount:
        valid_perms = {p.value for p in PermissionFlag}
        perms = [
            PermissionFlag(str(p))
            for p in (self.permissions or [])
            if str(p) in valid_perms
        ]
        density_val = str(self.density or "COMFORT").upper()
        theme_val = str(self.theme or "DARK").upper()
        policy_val = str(self.unreachable_policy or "DIM").upper()
        return UserAccount(
            id=self.id,
            username=self.username,
            display_name=self.display_name,
            default_remote_user=self.default_remote_user,
            ssh_template=self.ssh_template,
            permissions=perms,
            team_ids=[str(t) for t in (self.team_ids or [])],
            pinned_dashboard_ids=[str(d) for d in (self.pinned_dashboard_ids or [])],
            default_dashboard_id=self.default_dashboard_id or None,
            density=DensityMode(density_val if density_val in {"COMFORT", "COMPACT"} else "COMFORT"),
            theme=ThemeMode(theme_val if theme_val in {"DARK", "LIGHT"} else "DARK"),
            unreachable_policy=UnreachablePolicy(policy_val if policy_val in {"HIDE", "DIM"} else "DIM"),
        )

    @classmethod
    def from_domain(
        cls,
        domain: UserAccount,
        *,
        password_hash: str = "",
        auth_source: str = "local",
    ) -> UserAccountRecord:
        return cls(
            id=domain.id,
            username=domain.username,
            display_name=domain.display_name,
            default_remote_user=domain.default_remote_user,
            ssh_template=domain.ssh_template,
            password_hash=password_hash,
            auth_source=auth_source,
            permissions=[p.value for p in domain.permissions],
            team_ids=list(domain.team_ids),
            pinned_dashboard_ids=list(domain.pinned_dashboard_ids),
            default_dashboard_id=domain.default_dashboard_id,
            density=domain.density.value,
            theme=domain.theme.value,
            unreachable_policy=domain.unreachable_policy.value,
        )


class SystemSettingsRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True, default="default")
    default_global_dashboard_id = models.CharField(max_length=64)
    updated_by = models.CharField(max_length=128, default="joperator")
    updated_at = models.CharField(max_length=64, default="2026-11-01T00:00:00Z")

    class Meta:
        db_table = "panic_system_settings"

    def to_domain(self) -> SystemSettings:
        return SystemSettings(
            default_global_dashboard_id=self.default_global_dashboard_id,
            updated_by=self.updated_by,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_domain(cls, domain: SystemSettings, record_id: str = "default") -> SystemSettingsRecord:
        return cls(
            id=record_id,
            default_global_dashboard_id=domain.default_global_dashboard_id,
            updated_by=domain.updated_by,
            updated_at=domain.updated_at,
        )


class CatalogItemRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    protocol = models.CharField(max_length=32)
    host = models.CharField(max_length=512)
    port = models.IntegerField(null=True, blank=True)
    site = models.CharField(max_length=32, default="2SYA")
    path_or_args = models.CharField(max_length=512, blank=True, default="")
    custom_uri = models.CharField(max_length=512, blank=True, default="")
    account_override = models.CharField(max_length=128, blank=True, default="")
    tags = models.JSONField(default=_default_list, blank=True)
    normalized_key = models.CharField(max_length=512, db_index=True)
    scope = models.CharField(max_length=32, db_index=True, default="GLOBAL")
    team_ids = models.JSONField(default=_default_list, blank=True)
    owner_usernames = models.JSONField(default=_default_list, blank=True)
    zone_ids = models.JSONField(default=_default_list, blank=True)
    created_by = models.CharField(max_length=128, default="joperator")
    created_at = models.CharField(max_length=64, db_index=True, default="2026-11-01T09:00:00Z")

    class Meta:
        db_table = "panic_catalog_item"
        ordering = ["-created_at", "id"]

    def to_domain(self) -> CatalogItem:
        return CatalogItem(
            id=self.id,
            title=self.title,
            description=self.description,
            protocol=Protocol(str(self.protocol).upper()),
            host=self.host,
            port=int(self.port) if self.port is not None else None,
            site=self.site,
            path_or_args=self.path_or_args,
            custom_uri=self.custom_uri,
            account_override=self.account_override,
            tags=[str(t) for t in (self.tags or [])],
            normalized_key=self.normalized_key,
            scope=ScopeType(str(self.scope).upper()),
            team_ids=[str(t) for t in (self.team_ids or [])],
            owner_usernames=[str(u) for u in (self.owner_usernames or [])],
            zone_ids=[str(z) for z in (self.zone_ids or [])],
            created_by=self.created_by,
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, domain: CatalogItem) -> CatalogItemRecord:
        return cls(
            id=domain.id,
            title=domain.title,
            description=domain.description,
            protocol=domain.protocol.value,
            host=domain.host,
            port=domain.port,
            site=domain.site,
            path_or_args=domain.path_or_args,
            custom_uri=domain.custom_uri,
            account_override=domain.account_override,
            tags=list(domain.tags),
            normalized_key=domain.normalized_key,
            scope=domain.scope.value,
            team_ids=list(domain.team_ids),
            owner_usernames=list(domain.owner_usernames),
            zone_ids=list(domain.zone_ids),
            created_by=domain.created_by,
            created_at=domain.created_at,
        )


class EndpointListRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    scope = models.CharField(max_length=32, db_index=True, default="GLOBAL")
    team_ids = models.JSONField(default=_default_list, blank=True)
    owner_usernames = models.JSONField(default=_default_list, blank=True)
    item_ids = models.JSONField(default=_default_list, blank=True)
    created_by = models.CharField(max_length=128, default="joperator")
    created_at = models.CharField(max_length=64, db_index=True, default="2026-11-01T09:00:00Z")

    class Meta:
        db_table = "panic_endpoint_list"
        ordering = ["created_at", "id"]

    def to_domain(self) -> EndpointList:
        return EndpointList(
            id=self.id,
            title=self.title,
            description=self.description,
            scope=ScopeType(str(self.scope).upper()),
            team_ids=[str(t) for t in (self.team_ids or [])],
            owner_usernames=[str(u) for u in (self.owner_usernames or [])],
            item_ids=[str(i) for i in (self.item_ids or [])],
            created_by=self.created_by,
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, domain: EndpointList) -> EndpointListRecord:
        return cls(
            id=domain.id,
            title=domain.title,
            description=domain.description,
            scope=domain.scope.value,
            team_ids=list(domain.team_ids),
            owner_usernames=list(domain.owner_usernames),
            item_ids=list(domain.item_ids),
            created_by=domain.created_by,
            created_at=domain.created_at,
        )


class DashboardRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    scope = models.CharField(max_length=32, db_index=True, default="GLOBAL")
    team_ids = models.JSONField(default=_default_list, blank=True)
    owner_usernames = models.JSONField(default=_default_list, blank=True)
    always_display = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0, db_index=True)
    created_by = models.CharField(max_length=128, default="joperator")

    class Meta:
        db_table = "panic_dashboard"
        ordering = ["sort_order", "id"]

    def to_domain(self, widgets: list[DashboardWidget] | None = None) -> Dashboard:
        resolved_widgets: list[DashboardWidget]
        if widgets is not None:
            resolved_widgets = widgets
        else:
            db_widgets = [w.to_domain() for w in self.widget_records.order_by("sort_order", "id")]
            if db_widgets or self._state.adding is False:
                resolved_widgets = db_widgets
            else:
                resolved_widgets = list(getattr(self, "_domain_widgets", []))
        return Dashboard(
            id=self.id,
            title=self.title,
            description=self.description,
            scope=ScopeType(str(self.scope).upper()),
            team_ids=[str(t) for t in (self.team_ids or [])],
            owner_usernames=[str(u) for u in (self.owner_usernames or [])],
            always_display=bool(self.always_display),
            sort_order=int(self.sort_order),
            widgets=resolved_widgets,
            created_by=self.created_by,
        )

    @classmethod
    def from_domain(cls, domain: Dashboard) -> DashboardRecord:
        rec = cls(
            id=domain.id,
            title=domain.title,
            description=domain.description,
            scope=domain.scope.value,
            team_ids=list(domain.team_ids),
            owner_usernames=list(domain.owner_usernames),
            always_display=domain.always_display,
            sort_order=domain.sort_order,
            created_by=domain.created_by,
        )
        rec._domain_widgets = list(domain.widgets)
        return rec


class DashboardWidgetRecord(models.Model):
    # Surrogate PK: widget ids are client-generated and only unique within their dashboard.
    row_id = models.BigAutoField(primary_key=True)
    id = models.CharField(max_length=64, db_index=True)
    dashboard = models.ForeignKey(
        DashboardRecord,
        on_delete=models.CASCADE,
        related_name="widget_records",
        db_column="dashboard_id",
        db_index=True,
    )
    widget_type = models.CharField(max_length=32, default="HOST")
    title = models.CharField(max_length=255, blank=True, default="")
    grid_x = models.IntegerField(default=1)
    grid_y = models.IntegerField(default=1)
    grid_w = models.IntegerField(default=4)
    grid_h = models.IntegerField(default=1)
    catalog_item_id = models.CharField(max_length=64, null=True, blank=True)
    list_id = models.CharField(max_length=64, null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "panic_dashboard_widget"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["dashboard", "id"], name="uniq_widget_per_dashboard"),
        ]

    def to_domain(self) -> DashboardWidget:
        return DashboardWidget(
            id=self.id,
            dashboard_id=str(self.dashboard_id),
            widget_type=WidgetType(str(self.widget_type).upper()),
            title=self.title,
            grid_x=int(self.grid_x),
            grid_y=int(self.grid_y),
            grid_w=int(self.grid_w),
            grid_h=int(self.grid_h),
            catalog_item_id=self.catalog_item_id or None,
            list_id=self.list_id or None,
        )

    @classmethod
    def from_domain(cls, domain: DashboardWidget, sort_order: int = 0) -> DashboardWidgetRecord:
        return cls(
            id=domain.id,
            dashboard_id=domain.dashboard_id,
            widget_type=domain.widget_type.value,
            title=domain.title,
            grid_x=domain.grid_x,
            grid_y=domain.grid_y,
            grid_w=domain.grid_w,
            grid_h=domain.grid_h,
            catalog_item_id=domain.catalog_item_id,
            list_id=domain.list_id,
            sort_order=sort_order,
        )


class AuditLogRecord(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    actor_username = models.CharField(max_length=128, db_index=True)
    action = models.CharField(max_length=128, db_index=True)
    target_type = models.CharField(max_length=64, db_index=True)
    target_id = models.CharField(max_length=128)
    summary = models.TextField()
    details = models.JSONField(default=_default_dict, blank=True)
    created_at = models.CharField(max_length=64, db_index=True)

    class Meta:
        db_table = "panic_audit_log"
        ordering = ["-created_at", "-id"]

    def to_domain(self) -> AuditLogEntry:
        return AuditLogEntry(
            id=self.id,
            actor_username=self.actor_username,
            action=self.action,
            target_type=self.target_type,
            target_id=self.target_id,
            summary=self.summary,
            details=dict(self.details or {}),
            created_at=self.created_at,
        )

    @classmethod
    def from_domain(cls, domain: AuditLogEntry) -> AuditLogRecord:
        return cls(
            id=domain.id,
            actor_username=domain.actor_username,
            action=domain.action,
            target_type=domain.target_type,
            target_id=domain.target_id,
            summary=domain.summary,
            details=dict(domain.details),
            created_at=domain.created_at,
        )

"""Pydantic v2 conceptual data model for PANIC Stage 1."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Protocol(StrEnum):
    WEB = "WEB"
    SSH = "SSH"
    RDP = "RDP"
    LOCAL_APP = "LOCAL_APP"


class ScopeType(StrEnum):
    GLOBAL = "GLOBAL"
    TEAM = "TEAM"
    PERSONAL = "PERSONAL"


class PermissionFlag(StrEnum):
    GLOBAL_ADMIN = "GLOBAL_ADMIN"
    CAN_ADD_GLOBAL = "CAN_ADD_GLOBAL"
    CAN_ADD_TEAM = "CAN_ADD_TEAM"


class AuthSource(StrEnum):
    LOCAL = "LOCAL"
    OIDC = "OIDC"
    LDAP = "LDAP"


class WidgetType(StrEnum):
    HOST = "HOST"
    LIST = "LIST"


class DensityMode(StrEnum):
    COMFORT = "COMFORT"
    COMPACT = "COMPACT"


class ThemeMode(StrEnum):
    DARK = "DARK"
    LIGHT = "LIGHT"


class UnreachablePolicy(StrEnum):
    HIDE = "HIDE"
    DIM = "DIM"


class SecurityZone(BaseModel):
    id: str
    name: str
    description: str
    priority: int = 100
    cidrs: list[str] = Field(default_factory=list)
    builtin: bool = False
    created_at: str = "2026-11-01T00:00:00Z"
    updated_at: str = "2026-11-01T00:00:00Z"
    version: int = 1


class SiteDefinition(BaseModel):
    id: str
    code: str
    name: str
    description: str = ""
    created_at: str = "2026-11-01T00:00:00Z"
    updated_at: str = "2026-11-01T00:00:00Z"
    version: int = 1


class TeamDefinition(BaseModel):
    id: str
    name: str
    code: str
    description: str = ""
    members: list[str] = Field(default_factory=list)
    created_at: str = "2026-11-01T00:00:00Z"
    updated_at: str = "2026-11-01T00:00:00Z"
    version: int = 1


class CatalogItem(BaseModel):
    id: str
    title: str
    description: str = ""
    protocol: Protocol
    host: str
    port: int | None = None
    site: str = "2SYA"
    path_or_args: str = ""
    custom_uri: str = ""
    account_override: str = ""
    tags: list[str] = Field(default_factory=list)
    normalized_key: str
    scope: ScopeType = ScopeType.GLOBAL
    team_ids: list[str] = Field(default_factory=list)
    owner_usernames: list[str] = Field(default_factory=list)
    zone_ids: list[str] = Field(default_factory=list)
    search_keys: list[str] = Field(default_factory=list)
    orphaned: bool = False
    created_by: str = "joperator"
    created_at: str = "2026-11-01T09:00:00Z"
    updated_by: str = "joperator"
    updated_at: str = "2026-11-01T09:00:00Z"
    version: int = 1


class EndpointList(BaseModel):
    id: str
    title: str
    description: str = ""
    scope: ScopeType = ScopeType.GLOBAL
    team_ids: list[str] = Field(default_factory=list)
    owner_usernames: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)
    search_keys: list[str] = Field(default_factory=list)
    orphaned: bool = False
    created_by: str = "joperator"
    created_at: str = "2026-11-01T09:00:00Z"
    updated_by: str = "joperator"
    updated_at: str = "2026-11-01T09:00:00Z"
    version: int = 1


class DashboardWidget(BaseModel):
    id: str
    dashboard_id: str
    widget_type: WidgetType
    title: str = ""
    grid_x: int = 1
    grid_y: int = 1
    grid_w: int = 4
    grid_h: int = 1
    catalog_item_id: str | None = None
    list_id: str | None = None


#: A Material icon ligature name: lowercase letters, digits and underscores (e.g. ``router``).
DASHBOARD_ICON_RE = r"^[a-z0-9_]{1,40}$"


class Dashboard(BaseModel):
    id: str
    title: str
    description: str = ""
    scope: ScopeType = ScopeType.GLOBAL
    team_ids: list[str] = Field(default_factory=list)
    owner_usernames: list[str] = Field(default_factory=list)
    always_display: bool = False
    sort_order: int = 0
    icon: str = "dashboard"  # Material icon name shown in the menu (validated by DASHBOARD_ICON_RE)
    widgets: list[DashboardWidget] = Field(default_factory=list)
    search_keys: list[str] = Field(default_factory=list)
    orphaned: bool = False
    created_by: str = "joperator"
    updated_by: str = "joperator"
    updated_at: str = "2026-11-01T09:00:00Z"
    version: int = 1


class UserAccount(BaseModel):
    id: str
    username: str
    display_name: str
    default_remote_user: str
    ssh_template: str = "ssh {user}@{host} -p {port} {flags}"
    auth_source: AuthSource = AuthSource.LOCAL
    disabled: bool = False
    permissions: list[PermissionFlag] = Field(default_factory=list)
    team_ids: list[str] = Field(default_factory=list)
    pinned_dashboard_ids: list[str] = Field(default_factory=list)
    default_dashboard_id: str | None = None
    density: DensityMode = DensityMode.COMFORT
    theme: ThemeMode = ThemeMode.DARK
    unreachable_policy: UnreachablePolicy = UnreachablePolicy.DIM
    search_keys: list[str] = Field(default_factory=list)
    last_login_at: str | None = None
    updated_at: str = "2026-11-01T00:00:00Z"
    version: int = 1


#: URI scheme for the SSH system handler: lowercase, RFC 3986 scheme characters.
SSH_URI_SCHEME_RE = r"^[a-z][a-z0-9+.-]{1,31}$"


class SystemSettings(BaseModel):
    default_global_dashboard_id: str
    # SSH "open with system handler" (per-user URI handler): off removes the URI from every launch.
    ssh_uri_enabled: bool = True
    ssh_uri_scheme: str = "panic-ssh"
    updated_by: str = "joperator"
    updated_at: str = "2026-11-01T00:00:00Z"
    version: int = 1


class AuditLogEntry(BaseModel):
    id: str
    actor_username: str
    view_as_username: str | None = None
    action: str
    target_type: str
    target_id: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    client_ip: str = ""
    zone_id: str | None = None
    request_id: str | None = None
    created_at: str

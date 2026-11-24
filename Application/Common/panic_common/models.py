"""Pydantic v2 conceptual data model for PANIC."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Protocol(StrEnum):
    URL = "URL"
    SSH = "SSH"
    RDP = "RDP"
    LOCAL_APP = "LOCAL_APP"


#: Launch order of an item's connections: the first is the primary (the row click on a dashboard).
PROTOCOL_ORDER: tuple[Protocol, ...] = (Protocol.SSH, Protocol.RDP, Protocol.URL, Protocol.LOCAL_APP)
#: Protocols one item may not combine (both would claim the same remote console).
EXCLUSIVE_PROTOCOLS: frozenset[Protocol] = frozenset({Protocol.SSH, Protocol.RDP})


class ScopeType(StrEnum):
    GLOBAL = "GLOBAL"
    TEAM = "TEAM"
    PERSONAL = "PERSONAL"


class PermissionFlag(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"  # always with GLOBAL_ADMIN; hidden from non-super admins
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


class Connection(BaseModel):
    """One way to reach a catalog item's host: URL path, SSH flags or a local-app command per protocol."""

    protocol: Protocol
    port: int | None = None
    path_or_args: str = ""
    custom_uri: str = ""


def _legacy_connection(data: dict[str, Any]) -> dict[str, Any]:
    """The pre-0.2 single-protocol shape (``protocol``/``port``/``path_or_args``/``custom_uri``), WEB -> URL."""
    protocol = data.pop("protocol")
    return {
        "protocol": "URL" if protocol == "WEB" else protocol,
        "port": data.pop("port", None),
        "path_or_args": data.pop("path_or_args", ""),
        "custom_uri": data.pop("custom_uri", ""),
    }


class CatalogItem(BaseModel):
    id: str
    title: str
    description: str = ""
    host: str
    connections: list[Connection] = Field(min_length=1)  # in PROTOCOL_ORDER; the first is the primary
    site: str = "2SYA"
    account_override: str = ""
    tags: list[str] = Field(default_factory=list)
    normalized_keys: list[str]  # one per connection, for duplicate detection
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

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy(cls, data: Any) -> Any:
        """Accept a pre-0.2 document or export (one ``protocol``, one ``normalized_key``)."""
        if isinstance(data, dict) and "protocol" in data and "connections" not in data:
            data = dict(data)
            data["connections"] = [_legacy_connection(data)]
            key = data.pop("normalized_key", "")
            data["normalized_keys"] = [key.replace("web://", "url://", 1)] if key else []
        return data

    @property
    def primary(self) -> Connection:
        return self.connections[0]

    def connection(self, protocol: Protocol) -> Connection | None:
        return next((c for c in self.connections if c.protocol == protocol), None)


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
    density: DensityMode = DensityMode.COMPACT  # no longer exposed in the UI; the layout is always compact
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

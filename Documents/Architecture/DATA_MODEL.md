# PANIC — Data Model Specification

## 1. Overview
Defined as Pydantic v2 schemas in `panic_common.models`. In Stage 1, the data model is backed by an interactive state store (`panic_server.state`) with deterministic enterprise operations fixtures. Stage 2 persists these entities in a relational database (SQLite / PostgreSQL) via `DatabasePortalStore` while preserving the `panic_common.models` contract.

## 2. Core Entities

- **`Protocol` (StrEnum)**:
  - `WEB`, `SSH`, `RDP`, `LOCAL_APP`.
- **`ScopeType` (StrEnum)**:
  - `GLOBAL` (all users), `TEAM` (one or more `TeamDefinition` IDs), `PERSONAL` (individual operator usernames).
- **`PermissionFlag` (StrEnum)**:
  - `GLOBAL_ADMIN` (*Global Admin*), `CAN_ADD_GLOBAL` (*Can Add to Global Scope Items*), `CAN_ADD_TEAM` (*Can Add Team Scope Items*).
- **`WidgetType` (StrEnum)**:
  - `HOST` (Individual Host Card), `LIST` (Endpoint List Table Card).
- **`UserAccount` (`users`)**:
  - `id`, `username`, `display_name`, `default_remote_user`, `ssh_template`, `permissions` (`list[PermissionFlag]`), `team_ids` (`list[str]`), `pinned_dashboard_ids` (`list[str]`), `default_dashboard_id` (`str | None` — personal Default Dashboard UUID selected from accessible dashboards; `None` inherits `SystemSettings.default_global_dashboard_id`), `density` (`COMFORT` | `COMPACT`), `theme` (`DARK` | `LIGHT`), `unreachable_policy` (`HIDE` | `DIM`).
- **`SystemSettings` (`system_settings`)**:
  - `default_global_dashboard_id` (`str` — App-wide Default Global Dashboard UUID; must reference a `GLOBAL` scope `Dashboard`), `updated_by` (`str`), `updated_at` (`str`).
- **`SiteDefinition` (`sites`)**:
  - `id`, `code` (short uppercase site code, e.g., `2SYA`, `3MEL`, `4BNE`, `1CBR`), `name` (e.g., `Sydney Core DC`), `description`, `created_at`.
- **`TeamDefinition` (`teams`)**:
  - `id`, `code` (short uppercase code, e.g., `NETOPS`), `name`, `description`, `members` (`list[str]` usernames), `created_at`.
- **`SecurityZone` (`security_zones`)**:
  - `id`, `name`, `description`, `priority` (`int`), `cidrs` (`list[str]` of IPv4/IPv6 CIDR strings), `created_at`.
- **`CatalogItem` (`catalog_items`)**:
  - `id`, `title`, `description`, `protocol` (`WEB` | `SSH` | `RDP` | `LOCAL_APP`), `host` (hostname/IP for `SSH`/`RDP`, full URL for `WEB`, or executable command path for `LOCAL_APP`), `port` (`int | None` — defaults to `22` for `SSH`, `3389` for `RDP`, `None` for `LOCAL_APP`), `site` (references `SiteDefinition.code`), `path_or_args` (URL path for `WEB`, CLI flags for `SSH`, or CLI arguments for `LOCAL_APP`), `custom_uri`, `account_override`, `tags` (`list[str]`), `normalized_key`, `scope` (`ScopeType`), `team_ids` (`list[str]`), `owner_usernames` (`list[str]`), `zone_ids` (`list[str]` — empty means All Zones), `created_by`, `created_at`.
- **`EndpointList` (`endpoint_lists`)**:
  - `id`, `title`, `description`, `scope` (`ScopeType`), `team_ids` (`list[str]`), `owner_usernames` (`list[str]`), `item_ids` (ordered `list[str]` of `CatalogItem.id` values — must match `scope`, order is drag-and-drop customizable), `created_by`, `created_at`.
- **`Dashboard` (`dashboards`)**:
  - `id` (UUIDv4 string exposed in `<url>/dashboard/<dash-uuid>`), `title`, `description`, `scope` (`ScopeType`), `team_ids` (`list[str]`), `owner_usernames` (`list[str]`), `always_display` (`bool` — when `True` on a `GLOBAL` or `TEAM` dashboard, forces it onto the navigation menu for all users in scope), `sort_order` (`int`), `widgets` (`list[DashboardWidget]`), `created_by`.
  - **Default Dashboard Resolution Precedence**:
    1. `user.default_dashboard_id` (if set and visible in the user's scope) → source `"USER"`
    2. `system_settings.default_global_dashboard_id` (if visible in scope) → source `"SYSTEM_GLOBAL"`
    3. First visible dashboard in `sort_order` → source `"FALLBACK"`
- **`DashboardWidget` (`dashboard_widgets`)**:
  - `id`, `dashboard_id`, `widget_type` (`HOST` | `LIST`), `title`, `grid_x` (1–12), `grid_y`, `grid_w` (3–12, drag-resizable), `grid_h` (1–6, drag-resizable), `catalog_item_id` (for `HOST` widgets), `list_id` (for `LIST` widgets).
- **`AuditLogEntry` (`audit_logs`)**:
  - `id`, `actor_username`, `action`, `target_type`, `target_id`, `summary`, `details` (`dict[str, Any]`), `created_at`.

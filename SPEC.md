# PANIC — Portal for Accessing Networks, Infrastructure, and Compute

**Software Requirements & Staged Development Specification**  
**Version:** 1.0  
**License / Distribution:** Open-Source Enterprise Infrastructure Portal  

---

## 1. Executive Summary & Core Vision

**PANIC** (*Portal for Accessing Networks, Infrastructure, and Compute*) is a lightweight, self-hosted, multi-user enterprise operations portal and jump-host launcher. It acts as a centralized control plane and customizable launchpad for web applications, SSH endpoints, Remote Desktop (RDP) hosts, and local thick-client utilities.

### 1.1 Architectural Distinction
* **Control Plane & Launcher (Not an HTML5 Session Proxy):** Unlike heavy web-based bastions that proxy terminal or desktop video streams over WebSockets and store private keys or passwords on the server, PANIC renders a fast, minimal-JavaScript dashboard that hands off session execution directly to native tools on the operator's workstation or jump host (`ssh`, PuTTY, `mstsc.exe`, browser tabs, or local SOE binaries).
* **Zero Client Modification:** PANIC functions seamlessly on locked-down jump hosts without requiring custom OS URI protocol handlers, registry edits, browser extensions, or local client agents.
* **Vendor-Agnostic Open Source:** All documentation, UI labels, data models, and provider interfaces remain completely generic and vendor-neutral.

---

## 2. Reference Repositories & Style/Architecture Alignment

1. **Visual & UI Language Reference (`reference-project`):**
   * Adopts reference-ui's color palette, CSS variables, typography (`Inter` and `JetBrains Mono`), card borders, CVD-safe badges, spacing tokens, dark-first operations aesthetic, and component polish so PANIC feels like a sister application.
2. **Backend & Project Architecture Reference (`reference-project`):**
   * Mirrors `reference-app`'s repository directory layout (`Application/Common`, `Application/Server`, `Build/`, `Documents/`), `./panic` control script, environment configuration loading (`panic_server.conf`), structured JSON logging, Prometheus metrics, and strict separation of concerns (`import-linter` contract `AR-1.1`).

---

## 3. Staged Development Roadmap

Development proceeds in structured stages so UI ergonomics, layout density, and scope/RBAC workflows are validated before locking down relational persistence and external identity integrations.

### Stage 1: Interactive UI Scaffold & Mock State (Completed Baseline)
* **Deliverable:** A runnable web application implementing the complete UI, Zabbix-style 12-column full-width grid editor (`HOST` and `LIST` widgets), explicit bookmarkable URLs, Default Dashboard hierarchy, Command Palette (`Ctrl+K`), density/theme toggles, Catalog Items, Endpoint Lists, Pre-Defined Sites, Teams, Security Zones, and In-App RBAC with Admin `"View As"`—backed by an in-memory store (`MockPortalStore`) and deterministic fixtures.

### Stage 2: Relational Data Model, Persistence & Provisioning
* **Deliverable:** Relational database schema and Django ORM migrations (supporting SQLite for single-node deployments and PostgreSQL for enterprise HA), `DatabasePortalStore` repository implementation replacing the in-memory store, idempotent seed command (`manage.py panic_seed`), and declarative JSON/YAML export/import commands for catalog, list, zone, and dashboard provisioning.

### Stage 3: Enterprise Authentication, Trusted Proxy Zone Resolution & Security Hardening
* **Deliverable:** Session authentication with local bootstrap admin, pluggable OIDC/SSO and LDAP/LDAPS authentication backends with group-to-Team/RBAC claim mapping, trusted reverse-proxy source-IP and Security Zone resolution middleware, strict CSRF enforcement on all state-changing endpoints, Content-Security-Policy (CSP) headers, rate limiting, and filterable persistent audit logging.

### Stage 4: Containerization, Production Readiness & Operations Documentation
* **Deliverable:** Hardened multi-stage `Containerfile` (non-root user, static asset collection, Gunicorn workers), production `compose.yaml` with PostgreSQL, end-to-end smoke test suite, and operations documentation covering deployment, reverse proxies, configuration, and backup/restore.

### Stage 5: Pluggable Live Just-In-Time (JIT) Entitlement Providers (Future / Optional)
* **Deliverable:** Live external `EntitlementProvider` adapters (LDAP/AD recursive group lookup, RADIUS/AAA, OIDC/REST introspection) with short-TTL caching (default 30s), strict timeout fallback (default 3s), and soft/hard (`WARN` / `BLOCK`) launch gates.

---

## 4. Functional Requirements

### 4.1 Zabbix-Style Multi-Dashboard, Explicit URL Routing & Default Dashboards
* **Explicit Browser URLs (No Hidden URLs):**
  * Every screen and dashboard has an explicit, bookmarkable URL visible in the browser address bar via server-side route registration and HTML5 History (`pushState` / `replaceState` / `popstate`):
    * `<url>/` and `<url>/dashboard` — Resolve to the active user's effective **Default Dashboard** (`<url>/dashboard/<dash-uuid>`).
    * `<url>/dashboard/<dash-uuid>` — Specific dashboard in Locked (View) Mode, identified by a canonical UUIDv4 (`<dash-uuid>`).
    * `<url>/dashboard/<dash-uuid>/edit` — Specific dashboard in Unlocked (Edit) Mode.
    * `<url>/catalog`, `<url>/lists`, `<url>/sites`, `<url>/teams`, `<url>/zones`, `<url>/rbac`, `<url>/settings`, `<url>/profile`, `<url>/audit`.
* **Default Dashboard Hierarchy (User Default vs. App-Wide Default Global Dashboard):**
  * **User Default Dashboard (`user.default_dashboard_id`):** Users can select their personal Default Dashboard from the list of dashboards accessible to them (`GLOBAL`, their `TEAM`s, or `PERSONAL`) via the dashboard header (`Set as My Default` / `Reset`), Dashboard Properties modal, `/profile`, or `/settings`.
  * **App-Wide System Setting — Default Global Dashboard (`system_settings.default_global_dashboard_id`):** Global Admins can configure the application-wide **Default Global Dashboard** (must be a `GLOBAL` scope dashboard) on `/settings` or in Dashboard Properties. Any user who has not set a personal override automatically inherits the Default Global Dashboard. The active Default Global Dashboard is protected against deletion, unpinning, and scope demotion.
* **Full-Width Zabbix-Style 12-Column Grid:**
  * The main content panel spans 100% of available viewport width and resizes widget cards proportionally across a 12-column grid.
  * Dashboards load in **Locked (View) Mode** by default: clean, zero drag handles, zero resize grips, instant one-click launch actions.
  * Clicking **Edit Dashboard** (`/dashboard/<dash-uuid>/edit`) unlocks the layout grid, enabling drag-and-drop widget card reordering via the widget header bar, interactive width (`3..12` columns) and height (`1..6` rows) resizing via a bottom-right corner drag-resize handle (`.widget-resize-handle`), a **+ Add Widget** modal, **⚙ Dashboard Properties**, and **Save** / **Cancel** actions.
* **Dashboard Properties & Navigation Menu Pinning:**
  * Dashboards carry `id` (UUIDv4), `title`, `description`, `scope` (`GLOBAL`, `TEAM`, `PERSONAL`), `team_ids`, `owner_usernames`, and `always_display` (`bool`).
  * When `always_display` is enabled on a `GLOBAL` or `TEAM` dashboard, it is automatically pinned onto the left-hand Dashboards menu for all users in scope and cannot be removed while enabled.
  * Clicking `+` next to `Dashboards` in the left navigation rail opens a modal supporting both **Add Existing (Global / Team)** and **+ Create New** dashboards.
* **Two Dashboard Widget Types (`HOST` and `LIST`):**
  1. **Individual Host Card (`HOST`):** Displays protocol badge + icon (`WEB`, `SSH`, `RDP`, `LOCAL_APP`), Title, protocol-aware target row (`URL` for `WEB`, `Command` for `LOCAL_APP`, `Host` for `SSH`/`RDP`), `Site` code, `Zone(s)`, `Type` (`Global` / `Team` / `Personal`), and a right-aligned `Launch` button.
  2. **Endpoint List Card (`LIST`):** Displays the List Title, Scope badge, item count, and a structured table (`Type+Icon | Target (Host / URL / Command) | Site | Zone(s) | Type | Launch`) supporting interactive drag-and-drop row reordering (`⠿`).
* **Modern Operations UX (Minimal-JS):**
  * **Command Palette (`Ctrl+K` or `/`):** Instant keyboard-driven fuzzy search across dashboards, catalog items, and endpoint lists; pressing `Enter` triggers the primary launch/copy action immediately.
  * **Density & Theme Toggles:** Switch between *Comfort* and *Compact* density, and between *Dark* (default) and *Light* themes.

### 4.2 Supported Endpoint Protocols & Zero-Install Launchers
Every Catalog Item supports one of four protocols with protocol-specific target fields:

1. **Web Application (`WEB`):**
   * Fields: Title, Description, Target URL (`http://` or `https://`), Pre-Defined Site (`SiteDefinition.code`), Zone & Scope restrictions, Tags.
   * Action: Opens in a new browser tab (`target="_blank" rel="noopener noreferrer"`).
2. **Terminal / SSH (`SSH`):**
   * Fields: Title, Description, Hostname/IP, SSH Port (default `22`), Pre-Defined Site, Optional SSH Command Line Options / Flags (`path_or_args`), Optional Remote Username Override (`account_override`), Zone & Scope restrictions.
   * Primary Action (**Copy Command**): Interpolates `{host}`, `{port}`, `{user}`, and `{flags}` into the user's personal SSH Command Template (e.g., `ssh {user}@{host} -p {port} {flags}`) and copies to the clipboard with confirmation toast.
3. **Remote Desktop (`RDP`):**
   * Fields: Title, Description, Hostname/IP, RDP Port (default `3389`), Pre-Defined Site, Optional `Domain\Username` Override (`account_override`), Zone & Scope restrictions.
   * Primary Action (**Download `.rdp`**): Dynamically generates and streams an ephemeral plain-text `.rdp` file (`Content-Type: application/x-rdp`, `Cache-Control: no-store`) pre-populated with sanitized `full address:s:{host}:{port}` and `username:s:{resolved_user}`. Never written to server disk.
4. **Local Thick-Client / Custom Launcher (`LOCAL_APP`):**
   * Fields: Title, Description, Command / Executable Path (`host`), Command Line Options / Arguments (`path_or_args`) — with no Host/IP or Port fields — Pre-Defined Site, Optional Custom URI (`custom_uri`), Zone & Scope restrictions.
   * Primary Action (**Copy Launch Command** / **URI Trigger**): Copies the interpolated command line (`{host}`, `{user}`, `{args}`) or triggers the optional custom URI.

### 4.3 Catalog Items, Endpoint Lists, Pre-Defined Sites & Hygiene
* **Unified Scope Model (`GLOBAL`, `TEAM`, `PERSONAL`):**
  * Applied consistently across Catalog Items, Endpoint Lists, and Dashboards.
  * Both **Catalog Items (`/catalog`)** and **Endpoint Lists (`/lists`)** present two cards: Card 1 for **Global & Team** resources and Card 2 for **Personal** resources.
* **Endpoint Lists (`/lists`) & Same-Scope Enforcement:**
  * Operators curate ordered lists of Catalog Items to display inside dashboard `LIST` widgets.
  * **Strict Same-Scope Rule (`SCOPE_MISMATCH`):** An Endpoint List may only contain Catalog Items with the exact same `ScopeType` (`GLOBAL`, `TEAM`, or `PERSONAL`).
  * Items within an Endpoint List can be reordered via drag-and-drop (`⠿`) directly in list tables or inside the Edit/Define List modal (`POST /api/v1/lists` with `action: "reorder"`).
* **Pre-Defined Sites (`/sites`):**
  * Managed directory of site definitions (`code`, `name`, `description`, e.g., `2SYA`, `3MEL`, `4BNE`, `1CBR`) selected via dropdown when creating or editing Catalog Items.
* **Normalization, Deduplication & Credential Hygiene Engine:**
  * Computes a deterministic `normalized_key` per protocol (`web://`, `ssh://`, `rdp://`, `local_app://`) by lowercasing hostnames, stripping trailing slashes, and resolving default ports (`80/443/22/3389`), warning on duplicates within the same scope.
  * Rejects submissions containing embedded credentials (`user:pass@host`) or plaintext password flags (`-pw`, `--password`, `sshpass`).

### 4.4 Security Zones & Source IP Reachability
* **Security Zone Definitions (`/zones`):**
  * Global Admins define named **Security Zones** (`name`, `description`, `priority`, and IPv4/IPv6 CIDR blocks).
  * On each request, PANIC resolves the connecting jump host's source IP (honoring configured trusted reverse-proxy headers) against defined Zone CIDRs using longest-prefix match, breaking ties by highest `priority`.
  * Includes an interactive **Test IP Address** diagnostic tool on `/zones`.
* **Zone Reachability Filtering:**
  * Catalog Items can be marked **All Zones** (`zone_ids=[]`) or restricted to one or more selected Security Zones.
  * Items unreachable from the operator's active Zone are either dimmed (`UnreachablePolicy.DIM`) with an `Unavailable from <Zone>` badge or hidden (`UnreachablePolicy.HIDE`) based on user preference.

### 4.5 Teams, In-App RBAC & Admin "View As"
* **Teams (`/teams`):**
  * Directory of operational teams (`code`, `name`, `description`, `members[]`) governing visibility of `TEAM`-scoped Catalog Items, Endpoint Lists, and Dashboards.
* **In-App RBAC Permissions (`/rbac`):**
  * `GLOBAL_ADMIN` (*Global Admin*): Full administrative access to System Settings, Pre-Defined Sites, Teams, Security Zones, RBAC permissions, and all scopes; enables the **"View As"** switcher.
  * `CAN_ADD_GLOBAL` (*Can Add to Global Scope Items*): Create/edit `GLOBAL` Catalog Items, Endpoint Lists, and Dashboards.
  * `CAN_ADD_TEAM` (*Can Add Team Scope Items*): Create/edit `TEAM` Catalog Items, Endpoint Lists, and Dashboards for the user's teams.
  * All authenticated users can create and manage `PERSONAL` Catalog Items, Endpoint Lists, and Dashboards.
* **Admin "View As" Perspective Switcher:**
  * Users with `GLOBAL_ADMIN` permission can preview the entire portal (dashboards, left-rail navigation, catalog items, and endpoint lists) from the perspective of any other user account via the top bar or `/rbac`, with a one-click **Exit View As** banner.

---

## 5. Non-Functional & Security Requirements

1. **Minimal Client Footprint:** Server-rendered HTML shell hydrated with JSON state and dependency-free vanilla JavaScript (`panic.js`) and CSS (`app.css`). Zero frontend build-chain bloat.
2. **Injection & File Safety:**
   * Strict parameter sanitization (`sanitize_launch_param`) strips `\r`, `\n`, NUL, and control characters (`0x00–0x1F`, `0x7F`) from all `.rdp` and CLI template interpolations.
   * Ephemeral `.rdp` generation in memory (`Cache-Control: no-store`), never written to disk.
   * Zero storage of user passwords, private SSH keys, or secret tokens in catalog items or lists.
3. **Observability & Configuration:**
   * All configuration loaded from `PANIC_*` (and `PANIC_*_FILE`) environment variables (`panic_server.conf`).
   * Structured JSON logging with `X-Request-ID` correlation, plus `/api/v1/health`, `/api/v1/version`, and `/metrics` (Prometheus).

---

## 6. Core Data Model (`panic_common.models`)

* **`UserAccount`**: `id`, `username`, `display_name`, `default_remote_user`, `ssh_template`, `permissions` (`list[PermissionFlag]`), `team_ids`, `pinned_dashboard_ids`, `default_dashboard_id` (nullable UUID), `density` (`COMFORT`|`COMPACT`), `theme` (`DARK`|`LIGHT`), `unreachable_policy` (`HIDE`|`DIM`)
* **`SystemSettings`**: `default_global_dashboard_id` (UUID referencing a `GLOBAL` dashboard), `updated_by`, `updated_at`
* **`SiteDefinition`**: `id`, `code`, `name`, `description`, `created_at`
* **`TeamDefinition`**: `id`, `code`, `name`, `description`, `members` (`list[str]`), `created_at`
* **`SecurityZone`**: `id`, `name`, `description`, `priority`, `cidrs` (`list[str]`), `created_at`
* **`CatalogItem`**: `id`, `title`, `description`, `protocol` (`WEB`|`SSH`|`RDP`|`LOCAL_APP`), `host`, `port` (nullable), `site`, `path_or_args`, `custom_uri`, `account_override`, `tags`, `normalized_key`, `scope` (`GLOBAL`|`TEAM`|`PERSONAL`), `team_ids`, `owner_usernames`, `zone_ids`, `created_by`, `created_at`
* **`EndpointList`**: `id`, `title`, `description`, `scope` (`GLOBAL`|`TEAM`|`PERSONAL`), `team_ids`, `owner_usernames`, `item_ids` (ordered `list[str]` of same-scope `CatalogItem.id`s), `created_by`, `created_at`
* **`Dashboard`**: `id` (UUIDv4), `title`, `description`, `scope` (`GLOBAL`|`TEAM`|`PERSONAL`), `team_ids`, `owner_usernames`, `always_display` (`bool`), `sort_order`, `widgets` (`list[DashboardWidget]`), `created_by`
* **`DashboardWidget`**: `id`, `dashboard_id`, `widget_type` (`HOST`|`LIST`), `title`, `grid_x` (1–12), `grid_y`, `grid_w` (3–12), `grid_h` (1–6), `catalog_item_id` (nullable), `list_id` (nullable)
* **`AuditLogEntry`**: `id`, `actor_username`, `action`, `target_type`, `target_id`, `summary`, `details`, `created_at`

# PANIC — Portal for Accessing Networks, Infrastructure, and Compute

**Software Requirements & Staged Development Specification**  
**Version:** 1.0  
**License / Distribution:** Open-Source Enterprise Infrastructure Portal  

---

## 1. Executive Summary & Core Vision

**PANIC** (*Portal for Accessing Networks, Infrastructure, and Compute*) is a lightweight, self-hosted, multi-user enterprise operations portal and jump-host launcher. It acts as a centralized control plane and customizable launchpad for web applications, SSH endpoints, Remote Desktop (RDP) hosts, and local thick-client utilities.

### 1.1 Architectural Distinction
* **Control Plane & Launcher (Not an HTML5 Session Proxy):** Unlike heavy web-based bastions that proxy terminal or desktop video streams over WebSockets and store private keys or passwords on the server, PANIC renders a fast, lightweight dashboard that hands off session execution directly to native tools on the operator's workstation or jump host (`ssh`, PuTTY, `mstsc.exe`, browser tabs, or local SOE binaries).
* **Zero Client Modification:** PANIC functions seamlessly on locked-down jump hosts without requiring custom OS URI protocol handlers, registry edits, browser extensions, or local client agents.
* **Vendor-Agnostic Open Source:** All documentation, UI labels, data models, and provider interfaces remain completely generic and vendor-neutral.

---

## 2. Reference Repositories & Style/Architecture Alignment

1. **Visual & UI Language Reference (`reference-project`):**
   * Adopts reference-ui's color palette, CSS variables, typography (`Inter` and `JetBrains Mono`), card borders, CVD-safe badges, spacing tokens, dark-first operations aesthetic, and component polish so PANIC feels like a sister application.
2. **Backend & Project Architecture Reference (`reference-project`):**
   * Mirrors `reference-app`'s repository directory layout (`Application/Common`, `Application/Server`, `Application/Web`, `Build/`, `Documents/`), `./panic` control script, environment configuration loading (`panic_server.conf`), structured JSON logging, Prometheus metrics, strict separation of concerns (`import-linter` contracts), and (Stage 6) the nginx web unit + stateless API server split, pymongo repository layer, and generated OpenAPI / TypeScript client.

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

> Stages 1–4 are complete. Stage 6 ([ADR-0001](Documents/Architecture/adr/0001-web-server-mongo-split.md)) replaces the Stage 1 server-rendered full-snapshot UI, the Stage 1 simulator, and the Stage 2 relational persistence. (Stage 5, JIT entitlements, was removed from scope.)

### Stage 6: Web/Server Split, MongoDB & Scoped API
* **Deliverable:** Two deployable units:
  * **panic-web**: nginx serving a Vue 3 + Quasar + TypeScript SPA. It proxies an allow-list of `/api/v1/…` and `/auth/…` paths to `PANIC_SERVER_URL`, so everything stays same-origin.
  * **panic-server**: a stateless Django + DRF JSON API, N replicas behind an internal load balancer.
* **Data:** **MongoDB only** (the existing HA replica set, `PANIC_MONGO_URI`), through a pymongo repository layer with indexes defined in code. Django sessions and rate limits are also stored in Mongo.
* **No full-state loading:**
  * Per-screen endpoints: `/api/v1/ui/bootstrap`, `/api/v1/ui/dashboards/{id}`, paged catalog and lists, and server-side Command Palette search.
  * Mutations return only the changed resource.
  * Lists and dashboards use optimistic concurrency (`version` + `If-Match`).
  * Payload budgets are tested.
* **Also in this stage:**
  * The RBAC / source-IP simulator is removed.
  * Multi-tier `X-Forwarded-For` trust is hardened, with an admin diagnostics view.
  * The OpenAPI contract is committed, with a CI drift check.
  * Two images are published.
  * A load test runs at 5,000 endpoints / 50 users.

### Deployment topology (Stage 6)

```text
user ─► corporate reverse proxy / LB ─► panic-web (nginx; one or more per network zone) ─► internal LB ─► panic-server × N ─► MongoDB replica set
```

* Several panic-web instances (one per zone or site) point at one internal server load balancer. Each unit has its own standalone compose file (`compose.standalone.web.yaml`, `compose.standalone.server.yaml`).
* The browser only ever talks to its own panic-web origin. The SPA uses relative URLs.
* Every proxy tier appends to `X-Forwarded-For`. panic-server trusts only `PANIC_TRUSTED_PROXY_CIDRS`, which must list every tier, and fails closed (`Documents/Architecture/ARCHITECTURE.md` §5).

---

## 4. Functional Requirements

### 4.1 Zabbix-Style Multi-Dashboard, Explicit URL Routing & Default Dashboards
* **Explicit Browser URLs (No Hidden URLs):**
  * Every screen and dashboard has an explicit, bookmarkable URL visible in the browser address bar via server-side route registration and HTML5 History (`pushState` / `replaceState` / `popstate`):
    * `<url>/` and `<url>/dashboard` — Resolve to the active user's effective **Default Dashboard** (`<url>/dashboard/<dash-uuid>`).
    * `<url>/dashboard/<dash-uuid>` — Specific dashboard in Locked (View) Mode, identified by a canonical UUIDv4 (`<dash-uuid>`).
    * `<url>/dashboard/<dash-uuid>/edit` — Specific dashboard in Unlocked (Edit) Mode.
    * `<url>/catalog`, `<url>/lists`, `<url>/sites`, `<url>/teams`, `<url>/zones`, `<url>/settings`, `<url>/profile`, `<url>/audit`.
    * `<url>/settings/users` (users management), `<url>/settings/users/<user-id>` (edit one user), `<url>/settings/orphans` (orphaned resources), `<url>/settings/client-ip` (client-IP diagnostics). `<url>/rbac` redirects to `<url>/settings/users` (Stage 6).
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
  2. **Endpoint List Card (`LIST`):** Displays the List Title, Scope badge, item count, and a structured table (`Type+Icon | Target (Host / URL / Command) | Site | Zone(s) | Type | Launch`). Rows cannot be reordered on the card; order changes only in the Edit List modal. A very long list shows its first `PANIC_LIST_WIDGET_MAX_ITEMS` rows and a "Show all" link (Stage 6).
* **Modern Operations UX:**
  * **Command Palette (`Ctrl+K` or `/`):** Instant keyboard-driven search across dashboards, catalog items, and endpoint lists. From Stage 6 the search runs on the server (`GET /api/v1/ui/search`, about 20 results at most), so the client never holds the full catalog. Pressing `Enter` triggers the primary launch/copy action immediately.
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
  * Items within an Endpoint List can be reordered via drag-and-drop (`⠿`) **only** inside the Edit/Define List modal. The modal saves the full ordered `item_ids` (`PUT /api/v1/lists/{id}` with `If-Match`, Stage 6).
  * From Stage 6 a list may only contain Catalog Items the editor can see.
* **Pre-Defined Sites (`/sites`):**
  * Managed directory of site definitions (`code`, `name`, `description`, e.g., `2SYA`, `3MEL`, `4BNE`, `1CBR`) selected via dropdown when creating or editing Catalog Items.
* **Normalization, Deduplication & Credential Hygiene Engine:**
  * Computes a deterministic `normalized_key` per protocol (`web://`, `ssh://`, `rdp://`, `local_app://`) by lowercasing hostnames, stripping trailing slashes, and resolving default ports (`80/443/22/3389`), warning on duplicates within the same scope.
  * Rejects submissions containing embedded credentials (`user:pass@host`) or plaintext password flags (`-pw`, `--password`, `sshpass`).

### 4.4 Security Zones & Source IP Reachability
* **Security Zone Definitions (`/zones`):**
  * Global Admins define named **Security Zones** (`name`, `description`, `priority`, and IPv4/IPv6 CIDR blocks).
  * On each request, PANIC resolves the connecting jump host's source IP against defined Zone CIDRs using longest-prefix match, breaking ties by highest `priority`.
  * The source IP is always the real client IP. PANIC walks the `X-Forwarded-For` chain from right to left, skipping only configured trusted proxies. There is no simulator or zone override in any environment (Stage 6).
  * **Default zone (Stage 6):** A built-in zone named **Default** always exists. It has no CIDRs and cannot be deleted. Clients whose location is unknown are placed in it: the direct peer is not a trusted proxy, the forwarding chain is malformed or contains only trusted proxies, or the IP matches no zone CIDR. Catalog Items can include Default in their zone restrictions.
  * Includes an interactive **Test IP Address** diagnostic tool on `/zones`.
  * Global Admins also get a **client-IP diagnostics** view. It shows the raw forwarding headers, each hop, each trust decision, and the resolved IP and zone.
* **Zone Reachability Filtering:**
  * Catalog Items can be marked **All Zones** (`zone_ids=[]`) or restricted to one or more selected Security Zones.
  * Items unreachable from the operator's active Zone are either dimmed (`UnreachablePolicy.DIM`) with an `Unavailable from <Zone>` badge or hidden (`UnreachablePolicy.HIDE`) based on user preference.

### 4.5 Teams, In-App RBAC & Admin "View As"
* **Teams (`/teams`):**
  * Directory of operational teams (`code`, `name`, `description`) governing visibility of `TEAM`-scoped Catalog Items, Endpoint Lists, and Dashboards. Members are shown read-only; from Stage 6, membership is set only on each user's edit page.
* **Users Management (`/settings/users`, Stage 6):**
  * Global Admins list, search, create (pre-provision) and disable users. Users are never deleted, so the audit trail stays intact, and disabled users cannot sign in.
  * The user edit page (`/settings/users/<user-id>`) sets display name, permission flags, **team membership**, and enabled/disabled. It also offers **View As** for that user.
  * Permissions mapped from IdP groups are shown locked and refreshed at each external sign-in. Manual grants are kept separately and survive sign-in. Sign-in never changes team membership.
* **In-App RBAC Permissions (managed on the users pages; `/rbac` redirects there in Stage 6):**
  * `GLOBAL_ADMIN` (*Global Admin*): Full administrative access to System Settings, Pre-Defined Sites, Teams, Security Zones, RBAC permissions, and all scopes; enables the **"View As"** switcher.
  * `CAN_ADD_GLOBAL` (*Can Add to Global Scope Items*): Create/edit `GLOBAL` Catalog Items, Endpoint Lists, and Dashboards.
  * `CAN_ADD_TEAM` (*Can Add Team Scope Items*): Create/edit `TEAM` Catalog Items, Endpoint Lists, and Dashboards for the user's teams.
  * All authenticated users can create and manage their own `PERSONAL` Catalog Items, Endpoint Lists, and Dashboards. Nobody else can edit or delete them, not even Global Admins.
* **Orphaned Resources (Stage 6):** A `TEAM` resource with no remaining teams (for example, after its team was deleted), or a `PERSONAL` resource with no enabled owner, is *orphaned*. Orphans are visible only to Global Admins and are read-only. An admin can only **assign** an orphan **to a user**, which makes it that user's `PERSONAL` resource, or **delete** it. Both actions are audited. `/settings/orphans` lists all orphans.
* **Admin "View As" Perspective Switcher:**
  * Users with `GLOBAL_ADMIN` permission can preview the entire portal (dashboards, left-rail navigation, catalog items, and endpoint lists) from the perspective of any other user account via the top bar or `/rbac`, with a one-click **Exit View As** banner.
  * View As changes only the permissions and data perspective, never the Security Zone. It is stored in the admin's server-side session and audited.
  * View As is read-only: every mutation except leaving View As is refused while it is active (Stage 6).
* **Identity (Stage 6):** Users are always identified by a real sign-in: the local bootstrap admin, OIDC, or LDAP. The Stage 1 RBAC / source-IP simulator is removed from every environment.

---

## 5. Non-Functional & Security Requirements

1. **Lean, Scoped Client (Stage 6):** A Vue 3 + Quasar + TypeScript single-page application, served as static files by panic-web.
   * Each view fetches only the data it shows, from scoped JSON endpoints.
   * No endpoint returns or loads the full portal state.
   * Payload sizes are budgeted and tested.
   * This supersedes Stages 1–4, which used a server-rendered shell hydrated with the full state snapshot and vanilla `panic.js`.
2. **Injection & File Safety:**
   * Strict parameter sanitization (`sanitize_launch_param`) strips `\r`, `\n`, NUL, and control characters (`0x00–0x1F`, `0x7F`) from all `.rdp` and CLI template interpolations.
   * Ephemeral `.rdp` generation in memory (`Cache-Control: no-store`), never written to disk.
   * Zero storage of user passwords, private SSH keys, or secret tokens in catalog items or lists.
3. **Observability & Configuration:**
   * All configuration loaded from `PANIC_*` (and `PANIC_*_FILE`) environment variables (`panic_server.conf`). panic-web needs only `PANIC_SERVER_URL`.
   * Structured JSON logging with `X-Request-ID` correlation.
   * Endpoints: `/api/v1/health` (`?ready=1` also checks MongoDB), `/api/v1/version`, and `/metrics` (Prometheus; served by panic-server only, not proxied).
4. **Scalability & Statelessness (Stage 6):**
   * panic-server keeps no per-process user state. Sessions, rate-limit counters and audit records live in MongoDB, so any replica can serve any request.
   * Lists and dashboards use optimistic concurrency (`version` + `If-Match`; `409` on conflict).
   * Reference load: 5,000 endpoints and 50 concurrent users, within the p95 targets in `Documents/TASKS.md` (`T-S6-14`).
5. **Authorization (Stage 6):**
   * Every endpoint declares its access level: public, authenticated, or admin.
   * A resource the caller cannot see is reported as not found.
   * Editing requires the scope permission plus team membership or ownership (`Documents/Architecture/DATA_MODEL.md` §6).

---

## 6. Core Data Model (`panic_common.models`)

> Stage 6 persists these in MongoDB collections. Shapes, indexes, `version` and audit retention are in `Documents/Architecture/DATA_MODEL.md`. Team membership is held only in `UserAccount.team_ids`, set on the user edit page (`TeamDefinition.members` is removed). Users gain `idp_permissions` and `disabled`. Catalog items, lists and dashboards gain an `orphaned` flag. New ids are UUIDv4.

* **`UserAccount`**: `id`, `username`, `display_name`, `default_remote_user`, `ssh_template`, `permissions` (`list[PermissionFlag]`), `team_ids`, `pinned_dashboard_ids`, `default_dashboard_id` (nullable UUID), `density` (`COMFORT`|`COMPACT`), `theme` (`DARK`|`LIGHT`), `unreachable_policy` (`HIDE`|`DIM`)
* **`SystemSettings`**: `default_global_dashboard_id` (UUID referencing a `GLOBAL` dashboard), `updated_by`, `updated_at`
* **`SiteDefinition`**: `id`, `code`, `name`, `description`, `created_at`
* **`TeamDefinition`**: `id`, `code`, `name`, `description`, `members` (`list[str]`; removed in Stage 6, see `UserAccount.team_ids`), `created_at`
* **`SecurityZone`**: `id`, `name`, `description`, `priority`, `cidrs` (`list[str]`), `created_at`
* **`CatalogItem`**: `id`, `title`, `description`, `protocol` (`WEB`|`SSH`|`RDP`|`LOCAL_APP`), `host`, `port` (nullable), `site`, `path_or_args`, `custom_uri`, `account_override`, `tags`, `normalized_key`, `scope` (`GLOBAL`|`TEAM`|`PERSONAL`), `team_ids`, `owner_usernames`, `zone_ids`, `created_by`, `created_at`
* **`EndpointList`**: `id`, `title`, `description`, `scope` (`GLOBAL`|`TEAM`|`PERSONAL`), `team_ids`, `owner_usernames`, `item_ids` (ordered `list[str]` of same-scope `CatalogItem.id`s), `created_by`, `created_at`
* **`Dashboard`**: `id` (UUIDv4), `title`, `description`, `scope` (`GLOBAL`|`TEAM`|`PERSONAL`), `team_ids`, `owner_usernames`, `always_display` (`bool`), `sort_order`, `widgets` (`list[DashboardWidget]`), `created_by`
* **`DashboardWidget`**: `id`, `dashboard_id`, `widget_type` (`HOST`|`LIST`), `title`, `grid_x` (1–12), `grid_y`, `grid_w` (3–12), `grid_h` (1–6), `catalog_item_id` (nullable), `list_id` (nullable)
* **`AuditLogEntry`**: `id`, `actor_username`, `action`, `target_type`, `target_id`, `summary`, `details`, `created_at`

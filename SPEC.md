# PANIC — Portal for Accessing Networks, Infrastructure, and Compute

**Product specification.** This document describes PANIC as built. The enforced architecture rules
(`AR-x.y`) are in [`Documents/Architecture/ARCHITECTURE.md`](Documents/Architecture/ARCHITECTURE.md),
the HTTP contract in [`API.md`](Documents/Architecture/API.md) (authoritative form: the generated
OpenAPI document), and storage in [`DATA_MODEL.md`](Documents/Architecture/DATA_MODEL.md). Where this
page and those disagree, they win.

---

## 1. Purpose and principles

PANIC is a self-hosted, multi-user operations portal and session launcher. Operators get dashboards
of the web applications, SSH and RDP hosts, and local tools they use, and launch them in one click.

- **Launcher, not a session proxy.** PANIC never streams terminals or desktops. It hands each launch to
  a native tool on the operator's workstation or jump host: a browser tab, `ssh` or PuTTY, `mstsc.exe`,
  or a local application (AR-1.2).
- **No client modification.** Launches use standard browser navigation, the clipboard, optional
  standard URI schemes, or a downloaded `.rdp` file. No agent, extension or registry change is
  required (AR-1.3).
- **No stored credentials.** Catalog items never hold passwords, private keys or tokens, and
  submissions that contain them are rejected (AR-2.1).
- **Vendor-neutral.** Labels, data and interfaces are generic.

## 2. Architecture overview

```text
browser ─► reverse proxy / LB ─► panic-web (nginx, one or more) ─► internal LB ─► panic-server × N ─► MongoDB replica set
```

| Unit | What it is | Notes |
|---|---|---|
| **panic-web** | nginx serving the Vue 3 + Quasar + TypeScript single-page application | Proxies only the allow-listed server paths in `Application/Web/proxy-paths.json` (AR-6.4); everything else under `/api/` or `/auth/` is `404`. Needs only `PANIC_SERVER_URL`. Serves `/healthz` itself. |
| **panic-server** | Django + Django REST Framework JSON API under Gunicorn | Stateless; any number of replicas. Never renders HTML pages or serves the SPA. Serves Prometheus `/metrics` on its own port only. |
| **MongoDB** | The only datastore | Domain data, sessions, rate-limit counters and the audit log. Indexes are defined in code. |

- The browser talks only to its own panic-web origin, using relative URLs, so the deployment is
  same-origin (AR-1.6). Several panic-web instances (for example one per network zone or site) can
  share one server pool.
- Server code is layered `api` → `services` → `store`. Only `store` touches MongoDB. Shared domain
  rules (models, scope visibility, edit rights, normalisation, hygiene, zone and client-IP resolution,
  launch interpolation) live in the pure library `panic_common`, which has no I/O. These boundaries are
  enforced by import-linter contracts (ARCHITECTURE.md §7).
- The API is versioned under `/api/v1`. The OpenAPI 3.1 document is generated from the server and
  committed; the SPA's TypeScript types are generated from it, and CI fails on drift (AR-6.3).
- Design rationale: [ADR-0001](Documents/Architecture/adr/0001-web-server-mongo-split.md).

## 3. Concepts

| Concept | Meaning |
|---|---|
| **Catalog item** | One launchable host with one or more protocols (`URL`, `SSH`, `RDP`, `LOCAL_APP`; never both SSH and RDP), site, zones, tags, scope. |
| **Endpoint list** | An ordered list of catalog items of the same scope, shown in dashboard `LIST` widgets. |
| **Dashboard** | A 12-column grid of `HOST` (one item) and `LIST` (one endpoint list) widgets. |
| **Scope** | `GLOBAL` (everyone), `TEAM` (members of the resource's teams) or `PERSONAL` (its owner). Applies to catalog items, lists and dashboards. |
| **Site** | A short code and name (for example `DC1`, "Primary data centre") attached to catalog items. |
| **Team** | A named group of users that `TEAM`-scoped resources are shared with. |
| **Security zone** | A named set of IPv4/IPv6 CIDRs. The caller's zone decides which items are reachable. |
| **Permission** | `SUPER_ADMIN`, `GLOBAL_ADMIN`, `CAN_ADD_GLOBAL`, `CAN_ADD_TEAM`, granted in the app. |
| **Orphan** | A `TEAM` resource with no teams left, or a `PERSONAL` resource with no enabled owner. |
| **View As** | A Global Admin previewing the portal as another user, from another zone, or both. |

## 4. Functional requirements

### 4.1 Dashboards, navigation and URLs

- **Bookmarkable URLs.** Every screen has its own URL, handled by the SPA router (history mode;
  panic-web answers unknown non-API paths with `index.html`) (AR-1.4):
  - `/` and `/dashboard` resolve to the user's effective default dashboard and canonicalise to
    `/dashboard/<uuid>`.
  - `/dashboard/<uuid>` (view) and `/dashboard/<uuid>/edit` (edit).
  - `/catalog`, `/lists`, `/sites`, `/teams`, `/zones`, `/settings`, `/profile`, `/audit`, `/login`.
  - `/settings/users`, `/settings/users/<id>`, `/settings/orphans`, `/settings/client-ip`.
  - `/rbac` redirects to `/settings/users`.
- **Default dashboard.** Resolved in order (AR-2.6):
  1. the user's own default, if set and visible (chosen with the star on the dashboard header, on
     `/profile`, or when creating a dashboard);
  2. the app-wide default, set by a Super Admin on `/settings`, which must be `GLOBAL`;
  3. the first visible dashboard.

  The app-wide default cannot be deleted, unpinned or moved out of `GLOBAL` scope
  (`409 PROTECTED_RESOURCE`).
- **Dashboards menu.** The left rail lists the user's pinned dashboards, every visible dashboard
  marked `always_display`, the app-wide default and the user's default (or every visible dashboard
  if the user has pinned none). `always_display` dashboards and the app-wide default cannot be
  unpinned. A `+` control adds an existing `GLOBAL`/`TEAM` dashboard to the menu or creates a new one.
  New dashboards start empty and are pinned for their creator.
- **Dashboard properties:** UUIDv4 `id`, title, description, Material icon, scope with teams or
  owners, `always_display`, sort order.
- **View and edit modes.** Dashboards open locked: no drag handles, one-click launch. Edit mode
  (`/dashboard/<uuid>/edit`) allows:
  - moving widgets by dragging the header and resizing from the corner (width 3–12 columns,
    height 1–6 rows; overlapping widgets are pushed down);
  - adding widgets and editing dashboard properties;
  - saving with optimistic concurrency. A stale save gets `409 VERSION_CONFLICT`, and the user
    reloads and re-applies.

  The server clamps the grid and checks that every referenced item or list is visible to the editor.
  A dashboard holds at most 100 widgets.
- **Widgets.**
  - `HOST` shows one item: protocol icon, title, target, site, zones, scope and its launch action.
  - `LIST` shows a list's title, scope and items as table rows, each with its launch action. Rows
    are ordered as in the list and cannot be reordered on the card. A list longer than
    `PANIC_LIST_WIDGET_MAX_ITEMS` (default 200) shows the first rows and a "Show all" link to the
    list on `/lists`.
  - A widget whose item or list was deleted, or is not visible to the viewer, renders as an
    "unavailable" placeholder.
- **Command palette** (`Ctrl+K`, or `/` outside a text field). Searches dashboards, catalog items and
  lists on the server (`GET /api/v1/ui/search`, at most 20 results, queries of 2+ characters, each
  word prefix-matched). `Enter` runs the selected item's launch action or opens the dashboard or list.
- **Theme.** Dark (default) or light, toggled in the top bar and saved per browser and in the user's
  profile. The layout is always compact; there is no density setting.

### 4.2 Protocols and launchers

A catalog item has one host and one or more protocols (`connections`), picked as checkboxes, so a
device with a web UI and SSH is one item. SSH and RDP exclude each other. Each protocol has its own
port and path/arguments/command. The first in the order SSH, RDP, URL, LOCAL_APP is the item's
**primary**: clicking the item launches it, and every other protocol gets its own icon button on the
row. Launch actions are computed on the server for the caller (their SSH template and default
remote user) and returned with each item.

| Protocol | Fields | Launch action |
|---|---|---|
| `URL` | Port, path, full URL override (Host may be typed as a URL) | **Open** in a new tab (`noopener noreferrer`). URL is the item's custom URI if set, otherwise `https://<host>[:<port>]<path>`. |
| `SSH` | Port (default 22), arguments (`{flags}`); item account override | **Copy command**: the user's SSH template (default `ssh {user}@{host} -p {port} {flags}`) with `{host}`, `{port}`, `{user}`, `{flags}` filled in. Optionally also a URI `<scheme>://<user>@<host>:<port>` for a local handler; a Global Admin can turn this off or change the scheme (default `panic-ssh`) on `/settings`. |
| `RDP` | Port (default 3389); item account override | **Download** `GET /api/v1/launch/rdp/<id>.rdp`: an `.rdp` file with `full address` and `username` set, generated in memory and sent as `application/x-rdp` with `Cache-Control: no-store`. Downloads are audited. |
| `LOCAL_APP` | Port, command template, custom URI; item account override | **Copy command**: the arguments template with `{host}`, `{port}`, `{user}` filled in. If a custom URI is set, it is offered as well. |

The remote user (`{user}`) is the item's account override if set, otherwise the caller's default
remote user. Every interpolated value is sanitised first (§5.2).

### 4.3 Catalog, endpoint lists, sites and hygiene

- **Catalog (`/catalog`) and lists (`/lists`)** each show two server-paged tables: shared
  (`GLOBAL` and `TEAM`) and personal. Tables support search, sorting, and filters (protocol, site,
  zone, team for the catalog).
- **Endpoint lists.**
  - A list may contain only items of its own scope (`400 SCOPE_MISMATCH`) that the editor can see.
  - Order is changed only in the list editor, which saves the full ordered item list
    (`PUT /api/v1/lists/<id>` with `If-Match`).
  - A list holds at most `PANIC_LIST_MAX_ITEMS` (default 500) items.
  - Deleting a catalog item removes it from every list.
- **Sites (`/sites`).** Global Admins manage site definitions (unique upper-case `code`, `name`,
  `description`). Items pick a site from a drop-down. Renaming a code updates the items that use it;
  the last site cannot be deleted.
- **Normalisation and duplicates.** Each of an item's protocols gets a deterministic key in
  `normalized_keys` (`url://`, `ssh://`, `rdp://`, `local_app://`): host lower-cased, trailing slashes
  removed, default ports filled in (80/443, 22, 3389). Creating an item that shares any key with a
  visible item of the same scope gives `409 DUPLICATE_CATALOG_ITEM` unless the request is resent with
  `force_allow_duplicate`. A preview endpoint shows the keys, hygiene result and any duplicate before
  saving.
- **Copy.** Catalog items, sites, teams and zones have a Copy action (between Edit and Delete) that
  opens the edit dialog prefilled from the row as a new record; Save stays disabled until something
  is changed.
- **Credential hygiene (AR-2.1).** Submissions are rejected (`400 CREDENTIAL_HYGIENE_VIOLATION`)
  when any field contains:
  - embedded credentials (`user:password@host`);
  - plaintext password flags (`-pw`, `--password`, `sshpass`, `password=`);
  - private key material;
  - an account override containing a colon or a space.

  A user's SSH template and default remote user are checked too (no password flags; the remote
  user may not contain credentials, colons or spaces).

### 4.4 Security zones and client IP

- **Zones (`/zones`).** Global Admins define zones (`name`, `description`, `priority`, up to 64
  IPv4/IPv6 CIDRs, validated and canonicalised). A **Test IP address** tool shows which zone an
  address resolves to and how many items it can reach.
- **Default zone.** A built-in zone named **Default** (`zone-default`) always exists. It has no CIDRs,
  cannot be deleted or renamed, and only its description can change. Every request has exactly one
  zone: a client whose location is unknown, or whose IP matches no zone, is in Default.
- **Zone resolution** (AR-2.4). The client IP is matched against zone CIDRs: longest prefix first,
  then the zone with the smallest total address space, then the higher `priority`, then the name.
- **Client IP resolution** (AR-5.3). The client IP always comes from the real connection; there is
  no simulator or override.
  1. If proxy headers are disabled (`PANIC_TRUST_PROXY_HEADERS=false`), the client is the direct
     peer.
  2. If the direct peer is not in `PANIC_TRUSTED_PROXY_CIDRS`, its headers are ignored. With the
     default policy the client is the peer, the location is unknown and the zone is Default; with
     `PANIC_UNTRUSTED_PEER_POLICY=reject` the request gets `403 UNTRUSTED_PEER` (health and version
     from loopback excepted).
  3. Otherwise PANIC reads `X-Forwarded-For` (or `Forwarded`, per `PANIC_PROXY_IP_HEADER`), limited
     to the right-most `PANIC_XFF_MAX_HOPS` hops and `PANIC_XFF_MAX_BYTES` bytes, and walks right to
     left, skipping trusted hops. The first untrusted hop is the client.
  4. A malformed hop (`unknown`, an obfuscated identifier, garbage) reached before an untrusted hop,
     a missing header, or a chain of only trusted hops means the location is unknown: zone Default.

  Every proxy tier must append to `X-Forwarded-For`, and `PANIC_TRUSTED_PROXY_CIDRS` must list every
  tier and nothing that can be a client (AR-5.1, AR-5.2).
- **Diagnostics.** Global Admins can open `/settings/client-ip`, which shows the raw headers, each
  hop and its trust decision, the decision reached, the resolved IP, the zone and the candidate zones.
- **Reachability.** An item is reachable from all zones (`zone_ids` empty) or from listed zones only
  (Default can be listed). Unreachable items follow the user's preference:
  - `DIM` (default): returned with a reason; dashboard widgets hide them until the widget's
    "Show Unavailable Items" box is ticked.
  - `HIDE`: omitted by the server.

### 4.5 Teams, users, permissions and View As

- **Teams (`/teams`).** Global Admins manage teams (unique `code`, `name`, `description`). Members are
  shown read-only; membership is set only on each user's page. Deleting a team removes it from users
  and resources and reports how many resources it orphaned.
- **Users (`/settings/users`, Global Admin).**
  - List, search, filter and pre-provision users. Users are never deleted; they are disabled.
    Disabled users cannot sign in and their sessions are ended.
  - The user page (`/settings/users/<id>`) sets display name, permissions, team membership and
    enabled/disabled, shows counts of owned resources, and starts View As for that user.
  - The last enabled Global Admin cannot lose that permission or be disabled.
- **Permissions.**
  - `SUPER_ADMIN`: everything `GLOBAL_ADMIN` can do (it always comes with it), plus application
    settings and config export/import (§4.7). The bootstrap admin is always a super admin; only super
    admins can edit it, and nobody can disable it or remove its admin roles. Only super admins see the
    role or grant it: to other admins a super admin is shown as a plain Global Admin, and their
    permission edits leave the hidden role in place. View As never grants it.
  - `GLOBAL_ADMIN`: sites, teams, zones, users, orphans, audit, client-IP diagnostics and View As.
    Sees every `TEAM` resource.
  - `CAN_ADD_GLOBAL`: create and edit `GLOBAL` items, lists and dashboards.
  - `CAN_ADD_TEAM`: create and edit `TEAM` items, lists and dashboards for teams the user belongs to.
  - Every signed-in user can create and manage their own `PERSONAL` resources.
- **Edit rights** (AR-2.7, DATA_MODEL.md §6).

  | Scope | Create | Edit or delete |
  |---|---|---|
  | `GLOBAL` | `CAN_ADD_GLOBAL` | `CAN_ADD_GLOBAL` |
  | `TEAM` | `CAN_ADD_TEAM` and member of every chosen team (Global Admin: any team) | `CAN_ADD_TEAM` and member of at least one of the resource's teams, before and after the change (Global Admin: any) |
  | `PERSONAL` | everyone (owner is self) | an owner only; Global Admins cannot edit other users' personal resources |
  | orphan | – | nobody |
- **Orphans (`/settings/orphans`).** Orphans are visible only to Global Admins and are read-only
  (`403 ORPHANED_RESOURCE` on edit). An admin can **assign** one to an enabled user, which makes it that
  user's `PERSONAL` resource (a list keeps only items that are that user's personal items), or
  **delete** it. Both are audited.
- **View As** (AR-2.9). A Global Admin can preview the portal as another user, from a chosen zone, or
  both (bootstrap reports `zone_source: VIEW_AS` when a zone is chosen). It is held in the admin's
  server-side session and shown as a banner with an exit action. While it is active every mutation
  except leaving View As is refused (`403 VIEW_AS_READ_ONLY`). Start and stop are audited, and audit
  entries written during View As record both users.

### 4.6 Authentication

- **Methods.**
  - **Local:** the bootstrap admin from `PANIC_BOOTSTRAP_ADMIN_USER` / `_PASSWORD` (a Super Admin,
    password hashed at rest). Can be turned off with `PANIC_AUTH_LOCAL_ENABLED=false`.
  - **LDAP / LDAPS:** username and password checked by bind after local accounts; certificates are
    validated unless `PANIC_LDAP_TLS_VERIFY=false`.
  - **OIDC:** authorization code flow with PKCE, `state` and `nonce`; `iss`, `aud`, `exp` validated.
    The redirect URI is `https://<panic-web host><PANIC_BASE_PATH>/auth/oidc/callback`.
- **Authentication only.** OIDC and LDAP establish identity and nothing else. A first external sign-in
  creates the user with no permissions and no teams; later sign-ins refresh only the display name and
  last sign-in time. IdP groups and claims are never mapped to permissions or teams (AR-2.11). An SSO
  or LDAP user can be promoted to Global Admin from the shell (`panic_user_admin promote`).
- **Sessions.** Server-side sessions in MongoDB; cookie `panic_sessionid` (`HttpOnly`,
  `SameSite=Lax`, `Secure` in production), lifetime `PANIC_SESSION_AGE_S` (default 8 hours).
- The sign-in page is an SPA route (`/login`); providers are discovered from
  `GET /api/v1/auth/providers`.

### 4.7 Administration and user settings

- **User settings (`/profile`):** display name, default remote user, SSH template, default dashboard,
  theme, unreachable-item policy.
- **Application settings (`/settings`):** app-wide default dashboard, SSH URI handler on/off and
  scheme (changed by Super Admins only; shown greyed out to others), config export/import (Super
  Admin), links to the admin pages.
- **Audit log (`/audit`, Global Admin).** Append-only record of every successful mutation, sign-in,
  View As change, `.rdp` download, config export and import, with actor, View As subject, target, client IP, zone and
  request id. Filterable by actor, action, target, text and time range; keyset-paged, newest first.
  Retained for `PANIC_AUDIT_RETENTION_DAYS` (default 365; `0` keeps entries forever). Each entry is
  also logged as JSON.
- **Config export and import (Super Admin, `/settings`).** *Export config* downloads sites, teams,
  zones, catalog items and lists, personal ones included (`format: panic-config`, `schema_version: 1`).
  *Import config* merges such a file and never deletes. Each record matches an existing one by id,
  else by natural key: sites and teams by code, zones by name, items and lists by title within their
  scope (personal: title and owners). Matched records are updated from the file, unmatched ones added
  with the file's id, so importing the same source again (e.g. reloading dev from prod) matches by id
  and adds no duplicates. Ambiguous, clashing or invalid records are skipped as conflicts; references
  (an item's teams and zones, a list's items) follow the matched records. A preview lists every
  addition, change (with fields) and conflict, then a confirmation applies it; it is refused if the
  data changed since the preview. Both are audited.
- **Full backup.** `manage.py panic_export` / `panic_import` keep the portable JSON format
  (`format: panic-export`, `schema_version: 2`) of everything including users (permissions and teams,
  no credentials), dashboards and settings; import upserts by id, or replaces everything with
  `--replace`. Password hashes, sessions, rate limits and the audit log are never exported.

## 5. Non-functional requirements

### 5.1 Scoped client and API

- No endpoint returns, and no request loads, the whole portal (AR-6.1). Each screen calls a scoped
  endpoint: `GET /api/v1/ui/bootstrap` once per page load, `GET /api/v1/ui/dashboards/<id>` per
  dashboard (each referenced item appears once), paged tables (page size at most 100), and the
  palette search.
- Mutations return only the changed resource with its new `version` and `ETag` (AR-6.6).
- Dashboard views send a weak `ETag` and answer `If-None-Match` with `304` (AR-6.7).
- Response sizes and MongoDB round trips per endpoint are budgeted and tested against a reference
  dataset of 5,000 catalog items, 50 users, 200 lists and 60 dashboards (AR-6.2, API.md §8).
- Errors use one JSON envelope: `error_code`, `detail`, optional `fields` (AR-3.4).

### 5.2 Injection and file safety

- Every value interpolated into an `.rdp` file or a command template passes through
  `sanitize_launch_param`, which strips CR, LF, NUL and other control characters
  (`0x00–0x1F`, `0x7F`) (AR-2.2).
- `.rdp` files are generated in memory per request, sent with `Cache-Control: no-store`, and never
  written to disk (AR-2.3).
- No user passwords for external accounts, private keys or secret tokens are stored with catalog
  items or lists.
- panic-web refuses paths with dot segments, encoded separators or empty segments, and limits request
  bodies to 1 MB.

### 5.3 Authorization and web security

- Every endpoint declares its access level: public, authenticated or admin. A test walks every URL
  and checks anonymous, user and admin outcomes (AR-2.8).
- A resource the caller cannot see is `404 NOT_FOUND`, never `403` (AR-2.7).
- CSRF: every unsafe method needs `X-CSRFToken` matching the `panic_csrftoken` cookie;
  `PANIC_CSRF_TRUSTED_ORIGINS` lists the public origin of every panic-web instance (AR-2.10).
- A strict `Content-Security-Policy` (`default-src 'self'`; overridable with `PANIC_CSP`),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy` and `Permissions-Policy` on every response.
- Rate limits, stored in MongoDB and keyed by resolved client IP: sign-in `PANIC_RATE_LIMIT_LOGIN`
  (default 10 per 60 s, per IP and per username) and unsafe API calls `PANIC_RATE_LIMIT_API`
  (default 300 per 60 s). Exceeding one gives `429` with `Retry-After`.
- In production (`PANIC_ENV=prod`) the server refuses to start with a weak or placeholder secret key.

### 5.4 Statelessness, scale and concurrency

- panic-server keeps no per-process user state. Sessions, rate-limit counters and the audit log are
  in MongoDB, so any replica serves any request and a load balancer may move a user between panic-web
  or panic-server instances mid-session without signing them out; no sticky sessions (AR-4.6, AR-4.7).
  The zone list may be cached per process for `PANIC_ZONE_CACHE_TTL_S` (default 10 s).
- Every mutable document carries a `version`; writes are compare-and-set. Dashboards and lists require
  `If-Match` (`428` if missing, `409 VERSION_CONFLICT` if stale); other resources honour it when sent
  (AR-4.5).
- **Performance targets** (p95, 50 concurrent users, 5,000 endpoints), measured by the load test in
  `Build/LoadTest`. Current results are in
  [`Documents/Operations/PERFORMANCE.md`](Documents/Operations/PERFORMANCE.md).

  | Request | p95 target |
  |---|---|
  | Bootstrap | ≤ 75 ms |
  | Dashboard view, typical | ≤ 150 ms |
  | Dashboard view, largest | ≤ 300 ms |
  | Dashboard view, `304` | ≤ 50 ms |
  | Palette search (per query) | ≤ 100 ms |
  | Catalog page | ≤ 120 ms |
  | List detail | ≤ 200 ms |
  | Mutations | ≤ 200 ms |

  Also: error rate below 0.1%, p99 at most 3 × p95, and panic-server CPU below 70% per replica at
  steady state.

### 5.5 Observability

- Structured JSON logs on stdout (`ts`, `level`, `component`, `logger`, `msg`, `request_id`), one
  access line per request. `X-Request-ID` is accepted or generated by panic-web, logged by the server
  and echoed in the response (AR-3.2).
- `GET /api/v1/health` (liveness; `?ready=1` adds a MongoDB ping and returns `503` on failure),
  `GET /api/v1/version`, and `GET /healthz` on panic-web (AR-3.3).
- `GET /metrics` (Prometheus: `panic_http_requests_total`, `panic_http_request_duration_seconds`)
  on panic-server's port only, never proxied by panic-web.

## 6. Deployment and configuration

- **Images.** `panic-web` and `panic-server`, both non-root on a read-only root filesystem with a
  health check. Compose files: `Build/Containers/compose.yaml` (full stack, configurable server
  replicas, optional bundled single-node MongoDB for demos) and standalone files for running web and
  server in different network zones. See
  [`Documents/Operations/DEPLOYMENT.md`](Documents/Operations/DEPLOYMENT.md).
- **Configuration.** Every setting is an environment variable (`PANIC_*`), and any of them can be
  supplied as `<NAME>_FILE` for secrets (AR-3.1). panic-web needs only `PANIC_SERVER_URL` (origin only,
  validated at start) and, if used, `PANIC_BASE_PATH`. panic-server needs at least `PANIC_MONGO_URI`;
  production also needs a strong `PANIC_DJANGO_SECRET_KEY`, `PANIC_ALLOWED_HOSTS`,
  `PANIC_CSRF_TRUSTED_ORIGINS` and `PANIC_TRUSTED_PROXY_CIDRS`. Full reference:
  [`Documents/Operations/CONFIGURATION.md`](Documents/Operations/CONFIGURATION.md).
- **URL prefix.** `PANIC_BASE_PATH` (for example `/panic`) runs PANIC below a path on a host name
  shared with other applications. It must be the same on panic-web and panic-server. The SPA, the API
  and `/auth/oidc/*` all move below it; the SPA learns the prefix from `<base href>`, so one image
  serves any prefix. The server puts the prefix on its redirects and `.rdp` links and scopes the
  session and CSRF cookies to it, and still answers unprefixed paths for health checks and `/metrics`.
  A prefix shares the origin with the other applications on that host name; use a dedicated host name
  where that matters.
- **MongoDB.** A replica set in production. Connection details, TLS and read preference go in the
  URI; the database is the URI path (default `panic`). On start each server replica ensures indexes
  and, when `PANIC_MIGRATE_ON_START=true`, runs the idempotent data migrations. Sessions read from the
  primary and write with `w=majority`.
- **Backup.** `mongodump` for full fidelity; the export format for provisioning and promotion between
  environments.

## 7. Data model

Domain models are Pydantic classes in `panic_common.models`, stored in MongoDB collections. Every
document has a string `_id` (UUIDv4 for new documents; exposed as `id`), and mutable documents carry
`version`, `created_at`/`updated_at` and `created_by`/`updated_by`. Field-level detail and indexes:
[`DATA_MODEL.md`](Documents/Architecture/DATA_MODEL.md).

| Collection | Main fields |
|---|---|
| `users` | `username`, `display_name`, `auth_source` (`LOCAL`/`OIDC`/`LDAP`), `default_remote_user`, `ssh_template`, `permissions`, `team_ids`, `disabled`, `pinned_dashboard_ids`, `default_dashboard_id`, `prefs` (`theme`, `unreachable_policy`), `last_login_at` |
| `sites` | `code`, `name`, `description` |
| `teams` | `code`, `name`, `description` (membership is `users.team_ids`) |
| `zones` | `name`, `description`, `priority`, `cidrs`, `builtin` |
| `catalog_items` | `title`, `description`, `host`, `connections` (embedded: `protocol`, `port`, `path_or_args`, `custom_uri`), `site`, `account_override`, `tags`, `normalized_keys`, `scope`, `team_ids`, `owner_usernames`, `zone_ids`, `orphaned`, `search_keys` |
| `endpoint_lists` | `title`, `description`, `scope`, `team_ids`, `owner_usernames`, `item_ids` (ordered), `orphaned`, `search_keys` |
| `dashboards` | `title`, `description`, `icon`, `scope`, `team_ids`, `owner_usernames`, `always_display`, `sort_order`, `widgets` (embedded: `id`, `widget_type`, `title`, `grid_x`, `grid_y`, `grid_w`, `grid_h`, `catalog_item_id` or `list_id`), `orphaned`, `search_keys` |
| `system_settings` | single document: `default_global_dashboard_id`, `ssh_uri_enabled`, `ssh_uri_scheme` |
| `audit_log` | `actor_username`, `view_as_username`, `action`, `target_type`, `target_id`, `summary`, `details`, `client_ip`, `zone_id`, `request_id` (TTL on `created_at`) |
| `sessions`, `rate_limits`, `schema_meta` | Server-side sessions, rate-limit windows, data-migration version |

Enumerations: `Protocol` (`URL`, `SSH`, `RDP`, `LOCAL_APP`), `ScopeType` (`GLOBAL`, `TEAM`,
`PERSONAL`), `PermissionFlag` (`SUPER_ADMIN`, `GLOBAL_ADMIN`, `CAN_ADD_GLOBAL`, `CAN_ADD_TEAM`), `WidgetType`
(`HOST`, `LIST`), `ThemeMode` (`DARK`, `LIGHT`), `UnreachablePolicy` (`HIDE`, `DIM`).

# Changelog

## 2026-11-25 — 0.3.1: version in the menu, release tags only move forward
- The left menu shows the running version ("v0.3.1") just above the pin, while the menu is pinned open.
- Release workflow: `X.Y` and `latest` move only when the release is the newest of its line / overall (by
  version), so releasing an older line or re-running an old tag never moves them back. `X.Y.Z` as before.

## 2026-11-24 — 0.3.0: Super Admin role, config export / merge-import
- New `SUPER_ADMIN` permission. The bootstrap admin is always a super admin (given the flag at sign-in);
  only super admins can edit it, and nobody can disable it or remove its admin roles. Super admins grant
  the role on the user page. Other admins never see it: super admins look like Global Admins to them,
  and their permission edits leave the role in place. View As never grants it.
- Application Settings: the default dashboard and SSH system handler can only be changed by super admins
  (greyed out for other admins; `PATCH /api/v1/settings` gives 403).
- Application Settings, super admins: **Export config** downloads sites, teams, zones, catalog items and
  lists (personal included) as `panic-config` JSON. **Import config** merges such a file: a preview lists
  additions, changes (with fields) and conflicts, a confirmation applies them, nothing is deleted.
  Records match by id, else by code (sites, teams), name (zones) or title within scope (items, lists);
  added records keep the file's ids, so re-importing the same source (e.g. prod into dev) never
  duplicates.
- Removed: `GET /api/v1/export` and the Settings "Export" link (it was Global Admin and included users).
  The full backup stays `manage.py panic_export` / `panic_import`.

## 2026-11-24 — 0.2.2: option to skip LDAP certificate verification
- New `PANIC_LDAP_TLS_VERIFY` (default `true`). `false` accepts any LDAPS / StartTLS certificate (self-signed,
  expired, wrong host name). The connection stays encrypted but the directory is not authenticated, so a
  host on the network path could impersonate it and read sign-in passwords; the server logs a warning once
  per process. Prefer `PANIC_LDAP_CA_CERT_FILE` with your CA where possible. Server only.

## 2026-11-24 — 0.2.1: View As refreshes the dashboard
- Starting or leaving View As (a zone, a user, or both) while on the dashboard it returns to left that
  dashboard as loaded before: items, including those in list widgets, kept showing as unavailable when the
  emulated zone allowed them. The dashboard now reloads whenever the effective user or zone changes. Web
  only; the server already applied the emulated zone.

## 2026-11-24 — 0.2.0: multi-protocol catalog items, Copy, side-by-side dialog buttons
- A catalog item can have more than one protocol, chosen as checkboxes in the item dialog, so a device
  with a web UI and SSH is one item. SSH and RDP are mutually exclusive. Each protocol has its own port and
  path / arguments / command. On dashboards, lists and the palette, clicking the item launches the primary
  protocol (SSH or RDP, else URL, else Local app); each other protocol gets an icon button on the row.
- The `WEB` protocol is now `URL` (normalized keys `url://…`).
- Data model: `catalog_items` replace `protocol`, `port`, `path_or_args`, `custom_uri` and `normalized_key`
  with `connections` (one `{protocol, port, path_or_args, custom_uri}` per protocol) and `normalized_keys`.
  `panic_migrate` step 2 converts existing items (runs on start unless `PANIC_MIGRATE_ON_START=false`);
  `ensure_indexes` drops the old `normalized_key_scope` and `protocol` indexes. Exports from earlier
  versions still import.
- API: `POST`/`PATCH /api/v1/catalog` and `POST /api/v1/catalog/preview` take `connections` instead of the
  single-protocol fields; preview returns `normalized_keys`. `ItemView` adds `protocols` and
  `alt_launches`. A duplicate is any shared key with a visible same-scope item. `PATCH /catalog/{id}`
  ignores fields that are not editable (it used to store them).
- Catalog items, sites, teams and zones have a Copy action between Edit and Delete: the edit dialog opens
  prefilled as a new record, and Save is enabled once something changes.
- The edit dialogs for catalog items, sites, teams and zones put Save and Cancel to the right of the
  fields instead of along the bottom.

## 2026-11-24 — 0.1.2: LDAP sign-in against Active Directory
- LDAP sign-in failed with 401 against Active Directory when the user search base was the domain root
  (e.g. `DC=example,DC=com`): AD adds referrals to its other partitions to the result, and PANIC counted them
  as extra matches. Only real entries count now; exactly one is still required.
- The "LDAP authentication unavailable" warning now includes the underlying error message (e.g. the
  certificate or connection failure), not only its type.

## 2026-11-24 — 0.1.1: panic-web starts on hosts without IPv6
- panic-web failed to start on a kernel with IPv6 disabled (`socket() [::]:8080 failed (97: Address family not
  supported by protocol)`): its nginx config always listened on `[::]:8080`. The entrypoint now adds the IPv6
  listener only when the kernel supports IPv6. No configuration change; replace the `panic-web` image.

## 2026-11-23 — 0.1.0, first public release
- Source published under GPL-3.0-or-later; images on GHCR: `ghcr.io/slinkysoftware/panic-web` and
  `ghcr.io/slinkysoftware/panic-server` (`0.1.0`, `0.1`, `latest`). A `vX.Y.Z` tag builds, smoke-tests (at `/`
  and under a URL prefix) and publishes both.

## 2026-11-23 — URL prefix (`PANIC_BASE_PATH`)
- PANIC can run under a path such as `/panic/` on a host name shared with other applications. One setting,
  the same on both tiers; empty keeps the previous behaviour at `/`.
- panic-web: every location sits below the prefix and forwards the full path; index.html's `<base href="/">`
  is rewritten to `<base href="/panic/">` (`sub_filter`). The SPA is built with relative asset URLs and takes
  the router base and API URLs from `<base href>`, so one image serves any prefix. Outside the prefix only
  `/healthz` answers. The entry script is renamed `10-panic-env.envsh` and validates both variables.
- panic-server: the prefix moves into `SCRIPT_NAME`; path checks use `path_info`; the login and OIDC
  redirects and the `.rdp` link carry the prefix; cookies are scoped to it. Requests without the prefix
  still work (health check, `/metrics`).
- CI also runs the joint smoke test under a prefix.

## 2026-11-19 — panic-web on nginx 1.30.7 (CVE-2026-123007, CVE-2026-123633)
- `panic-web` is built on the official `nginx:1.30.7-alpine` image instead of `nginx-unprivileged:1.29-alpine`.
  1.30.7 fixes two HTTP/2 bugs (flow-control heap overflow, proxy use-after-free); the 1.29 branch gets no fix
  and `nginx-unprivileged` had no 1.30.7 build. The image is set up the way `nginx-unprivileged` is (no `user`
  directive, pid and temp files in `/tmp`, uid 101, port 8080), so the container contract is unchanged.
  panic-web serves HTTP/1.1 only, so deployed images were not exposed.
- Upgrade: rebuild and redeploy `panic-web`.

## 2026-11-15 — Density setting removed; always compact
- Removed the top-bar density toggle and the Density field on User Settings: it was stored but never
  changed the layout. The UI is compact. The server keeps the stored `density` preference (unused), default
  now `COMPACT`.

## 2026-11-15 — View As a user and/or a zone
- `PUT /admin/view-as` takes `user_id` and/or `zone_id` (at least one). A zone overrides the IP-derived
  zone for reachability (`client.zone_source: VIEW_AS`); no user means the admin's own perspective from
  that zone. Mutations stay refused while any View As is active; exit clears both.
- The View As prompt is now a dialog with a user search and a zone picker; the banner shows the zone.

## 2026-11-15 — Zone specificity, example data commands, menu names
- Zone resolution: longest prefix wins; on a tie the zone with the smallest total address space wins
  (a zone that is just this /22 beats one spanning several networks), then higher `priority`, then name.
  The Zones page hint ("Lower wins") was wrong: priority is a tie-breaker and higher wins.
- `./panic addexamples` / `delexamples` (`manage.py panic_examples add|remove`) add or remove an example
  dataset (5 sites, 5 teams, 4 zones, 20 users, 120 items including routers, firewalls, switches and
  vCenter/ESXi/NSX/vRA; 23 lists, 7 dashboards; ids `example-*`, users `ex-*` without passwords, codes
  `EX-*`, documentation-only CIDRs) next to existing data. Adding is idempotent; removal deletes only the
  examples and strips references real data picked up (list items, dashboard widgets, team/zone ids, menu
  pins and defaults), keeping sites real items still use.
- Menu: "Settings" is now "Application Settings", "Profile" is "User Settings".

## 2026-11-15 — `./panic promote|demote <username>`
- New `manage.py panic_user_admin promote|demote <username>`, exposed as `./panic promote|demote` and
  `./panic user promote|demote`. The last enabled Global Admin cannot be demoted; changes are audited as
  `cli:<os user>`. `./panic manage` now loads `.env` like `start`.

## 2026-11-15 — Load test; search fix for seeded data
- `Build/LoadTest/` (`uv sync --group loadtest`): a Locust load test against the built images (1 web,
  2 servers, a separate database, 50 real sessions over 4 zones, steady state plus a stress run). Results
  in `Documents/Operations/PERFORMANCE.md`: no errors; p95 targets met except search and the catalog page;
  saturation is MongoDB-bound.
- Fix: `panic_seed` now gives seeded resources `search_keys` (seeded data was unsearchable).
- `./panic` dev-tools sync no longer uninstalls the load-test dependency group.

## 2026-11-15 — SSH launching: system URI handler and client presets
- Application Settings (Global Admin): "SSH system handler" switch and scheme (default `panic-ssh`). Off
  removes the SSH `launch.uri` everywhere; on, it is `<scheme>://user@host:port` (was `ssh://`).
  `PATCH /settings` takes any of the default dashboard and the two SSH fields.
- User Settings: when the handler is enabled, a setup section with a client choice (PuTTY / OpenSSH), a
  one-line PowerShell install command and a remove command. It writes `%LOCALAPPDATA%\PANIC\panic-ssh.ps1`
  and registers the scheme under `HKCU\Software\Classes` (no admin rights). The URL reaches the script only
  as a `-File` argument and is validated (`user@host:port`, no leading `-`, no quotes or spaces) before
  `Start-Process`; safe under Constrained Language mode.
- User Settings: "SSH client" dropdown (OpenSSH, PuTTY, Plink, Windows Terminal + OpenSSH, Custom) that
  fills the editable command template, with a live preview; editing the template switches to Custom.
- Header: "Portal for Accessing Networks, Infrastructure, and Compute" under the PANIC title.

## 2026-11-15 — Dashboard icons in the menu
- Dashboards carry an `icon` (Material icon name, default `dashboard`, validated server-side), set on
  create (`POST /dashboards`) and in edit mode's Dashboard details (`PATCH`), and returned in bootstrap
  navigation, dashboard summaries and views. The left menu and the Add dashboard list show it. The icon
  picker offers curated operations icons with search, or any valid icon name.

## 2026-11-15 — Operations and user documentation
- `CONFIGURATION.md` covers container init, gunicorn, panic-web, compose and dev variables, and lists
  removed variables; a test fails if any documented-as-removed variable is read again.
- `DEPLOYMENT.md` rewritten for the web/server split: topology, compose, replicas and migrations, a
  four-tier trusted-proxy worked example (including the L4 load balancer caveat), MongoDB URI and
  least-privilege role, `mongodump` and `panic_export` backups, monitoring, upgrades, dev workflow.
- `UI_DESIGN.md` and `README.md` updated.

## 2026-11-15 — Two container images, compose files, CI
- `panic-web` image: Node build stage, then nginx on port 8080 (read-only root filesystem supported). The
  server block is generated from `proxy-paths.json`: allow-listed paths only (`/metrics` and other API
  paths return 404), security headers and CSP, gzip, immutable `/assets/`, SPA fallback, `/healthz`.
  `PANIC_SERVER_URL` is validated (bare origin; `_FILE` supported).
- `panic-server` image: API only (no static files), gunicorn `gthread` workers, an init step
  (`panic_ensure_indexes`, plus `panic_migrate` when `PANIC_MIGRATE_ON_START`), and a `HEALTHCHECK` on
  `?ready=1` sending a Host that `PANIC_ALLOWED_HOSTS` accepts.
- `compose.yaml` (web, server with `PANIC_SERVER_REPLICAS`, `demo-mongo` profile),
  `compose.standalone.web.yaml`, `compose.standalone.server.yaml`.
- CI runs checks, a joint smoke test (two server replicas behind web; sign-in, allow-list, client IP from
  the forwarded chain, sessions across replicas and restarts) and builds and publishes both images.
  `./panic test` takes an externally supplied `PANIC_TEST_MONGO_URI`.

## 2026-11-15 — New web UI (Vue 3 + Quasar + TypeScript)
- New single-page app replacing the server-rendered UI: login page (local/LDAP form and OIDC button, driven
  by `GET /api/v1/auth/providers`), navigation rail driven by bootstrap (dashboard pins, default, locked;
  can be pinned open), top bar (zone badge, View As banner, theme toggle). API calls send the CSRF header
  with one retry; `401` redirects to `/login?next=...`. The API client is generated from the committed
  OpenAPI document. The dev proxy and panic-web share one path allow-list.
- Dashboards: `/dashboard/<id>` view with HOST and LIST widgets on a 12-column grid, launch actions (open
  URL, copy command, `.rdp` download, optional system URI), dimming of unreachable items, placeholders for
  unavailable targets, "Show all (N)", ETag revalidation, pin/unpin and set/reset my default. "Add
  dashboard" in the menu pins an existing dashboard or creates a new one.
- Dashboard edit mode (`/dashboard/<id>/edit`): drag to move, corner to resize, overlaps pushed down; Add
  Widget (skips targets already on the dashboard), widget properties, dashboard details and delete, Save
  with `If-Match` and a conflict banner (discard / overwrite), unsaved-changes guard. The server rejects
  the same item or list twice in a layout (`400 VALIDATION_ERROR`).
- Command Palette: Ctrl/Cmd+K, `/` outside text fields, or the Search button; server-side search, arrow
  keys, Enter launches an item or opens a dashboard or list.
- `/catalog`: Global & Team and Personal cards, server-paged with search, protocol/site/zone/team filters;
  protocol-aware item dialog with live preview, credential hygiene and field errors, and a duplicate
  prompt that can save anyway.
- `/lists`: same two cards; Edit List dialog with a same-scope item picker, drag or arrow reordering and
  `If-Match` saves with a conflict banner; read-only for non-editors; `?open=<id>` opens a list.
- Admin screens: Sites and Teams (search, create, edit, delete; writes for Global Admins only), `/zones`
  (CIDR chips, priority, built-in Default zone, Test IP), `/settings/users` (search; permission, team and
  status filters; pre-provision; disable / enable), `/settings/users/<id>` (display name, permissions, team
  membership, enable, View As, owned counts), team members dialog, `/settings/orphans` (assign to an
  enabled user, delete), `/settings` (app-wide default dashboard, export), `/profile`, `/audit` (filters in
  the URL, "Load more"), `/settings/client-ip` (summary, hop table, policy, raw headers).
- `./panic` manages two components (`web` on 8120, `server` on 8121), pins Node into `.tools/`
  (checksum-verified) and runs web lint, typecheck and unit tests. The web dev server allows this
  machine's host name; `PANIC_WEB_ALLOWED_HOSTS` adds extras.
- Fix: request ids fall back to `getRandomValues` outside secure contexts (plain-HTTP dev access).

## 2026-11-15 — New scoped REST API
- DRF-based API with a single error envelope, deny-by-default permission tiers (public, signed in, Global
  Admin), weak ETags / `304`, page and keyset pagination, and a committed OpenAPI document
  (`./panic contracts [--check]`).
- Endpoints: `/api/v1/auth/{providers,csrf,login,logout}`, `/api/v1/ui/{bootstrap,dashboards/{id},search}`,
  `/api/v1/launch/rdp/{id}.rdp`, `/me`, catalog, lists and dashboards CRUD (`If-Match` required on
  dashboards and lists; `428` / `409 VERSION_CONFLICT` with `current_version`), admin (sites, teams, zones,
  users, orphans, View As, settings), audit, export and `GET /api/v1/admin/client-ip` diagnostics.
- Authorization: user permission and team changes and audit are Global Admin only; duplicate checks and
  zone Test IP report only what the caller can see; list saves reject invisible or wrong-scope items;
  edit and delete enforce ownership and team membership. Orphaned resources are visible only to admins,
  read-only (`403 ORPHANED_RESOURCE`) and can only be assigned to a user or deleted. The default zone, the
  last site, the last admin and the app-wide default dashboard are protected.
- The old `/login` and `/logout` JSON endpoints are replaced by `/api/v1/auth/login` and `logout`.
- Fixes: login rate limiting no longer returns 500 on non-form POSTs; `?ready=1` on the health check is
  honoured; starting View As no longer drops its own session key; `last_login_at` and audit fields
  (View As user, client IP, zone, request id) are no longer lost on read; `./panic start` and the server
  container no longer call the removed relational `migrate` command.

## 2026-11-14 — Stateless request context; legacy SQL stack removed (breaking)
- Each request builds its own context (real and effective user, View As, client IP, forwarded-chain
  resolution, zone) with no process-wide state, so any replica can serve any request.
  `PANIC_UNTRUSTED_PEER_POLICY=reject` refuses requests from untrusted peers (`403 UNTRUSTED_PEER`;
  loopback health and version exempt).
- Sessions and rate limits (`login:ip`, `login:user`, `api:ip`) are stored in MongoDB.
- External sign-in (OIDC, LDAP) is used for authentication only: IdP groups no longer map to permissions
  or teams. A first sign-in gets no permissions or teams; later sign-ins update only display name and last
  login. Disabled users cannot sign in and their sessions are rejected.
- Removed the SQL/relational storage, the simulator, the server-rendered UI and its static assets.
  Removed settings: `PANIC_DB_*`, `PANIC_AUTO_SEED`, `PANIC_AUTH_MODE`, `PANIC_DEV_SIMULATOR_ENABLED`,
  `PANIC_CACHE_URL`, `PANIC_STATIC_ROOT`, `PANIC_SERVE_STATIC`, `PANIC_RBAC_*`, the OIDC groups claim and
  LDAP group search. Added `PANIC_UNTRUSTED_PEER_POLICY`, `PANIC_XFF_MAX_HOPS`, `PANIC_XFF_MAX_BYTES`.
- There is no migration from the SQL data model or import of v1 exports.

## 2026-11-14 — Seed, export and import on MongoDB
- `panic_seed`, `panic_export` and `panic_import` work on MongoDB with the same options as before
  (`--profile demo|loadtest`, `--reset` / `--if-empty`, `--output` / `--shared-only`, `--replace`).
- Export format `schema_version: 2`, sections sorted by `id` for byte-stable round-trips.
- Seed profiles: `demo` (small hand-built dataset) and `loadtest` (deterministic: 5,000 catalog items,
  50 users, 12 teams, 20 zones, 200 lists, 60 dashboards; documentation-only addresses and domains).

## 2026-11-14 — MongoDB storage
- New storage layer on MongoDB: idempotent index management (`panic_ensure_indexes`, TTL support),
  server-side visibility filtering, optimistic concurrency with a `version` field, MongoDB-backed sessions
  (primary reads, `w=majority` writes, continuity across processes) and fixed-window rate limits.
  `panic_migrate` creates the built-in Default zone and the system settings document.
- Data model: `version` / `updated_at` / `updated_by` on editable resources; `auth_source` and `disabled`
  on users; `orphaned` on catalog items, lists and dashboards; `builtin` on zones; `search_keys` for prefix
  search. New error codes: `VERSION_CONFLICT`, `PRECONDITION_REQUIRED`, `PROTECTED_RESOURCE`,
  `VIEW_AS_READ_ONLY`, `ORPHANED_RESOURCE`, `UNTRUSTED_PEER`, `PAYLOAD_TOO_LARGE`, `DATABASE_UNAVAILABLE`.
- Unknown client locations fall into a built-in Default zone. View As is read-only. Admins cannot edit
  other users' personal resources.
- Local dev MongoDB container (`panic-dev-mongo`, host port 27117), started by `./panic start` and
  `./panic test`.

## 2026-11-14 — Hardened X-Forwarded-For / Forwarded chain resolution
- The client IP is resolved by walking the hop chain right to left through trusted proxies, returning the
  hops, ignored left-hand hops, truncation, decision and whether the location is known (also shown in the
  client-IP diagnostics).
- Parses RFC 7239 `Forwarded` (`for=`, quoted/bracketed IPv6, ports, obfuscated identifiers) as well as
  `X-Forwarded-For`; normalises IPv4-mapped IPv6; enforces hop and byte limits.
- Untrusted peer, missing header, all hops trusted and malformed hop all mean an unknown location.
- Tested against four-tier chains, left-hand spoofing, untrusted-peer spoofing, overly broad trusted CIDRs,
  repeated header lines and junk tokens.

## 2026-11-14 — Security fix: authorization
- `POST /api/v1/rbac` (create and update user) now requires Global Admin. Before this fix, any signed-in
  user could grant themselves Global Admin.
- `GET /api/v1/audit` is Global Admin only (otherwise `403`); non-admins no longer receive audit entries
  in the portal snapshot.
- `GET /api/v1/launch/rdp/<id>.rdp` returns `404` for items the effective user cannot see.

## 2026-11-14 — Architecture for the web/server split
- Design documents for splitting PANIC into panic-web and panic-server on MongoDB with a scoped API:
  `ARCHITECTURE.md`, `DATA_MODEL.md`, `API.md` and an ADR. Covers statelessness and session continuity
  across replicas, the multi-tier `X-Forwarded-For` trust model, `If-Match` concurrency, payload budgets,
  per-screen endpoints, the proxy allow-list, server-side search, and a 365-day audit retention.

## 2026-11-14 — CI and image publishing
- CI runs the test suite on pushes and pull requests, builds the `panic-server` image, smoke-tests it in
  production mode and publishes it to the container registry: `:main` and `:sha-<short>` from `main`;
  `:X.Y.Z`, `:X.Y` and `:latest` from `vX.Y.Z` tags.
- The container no longer seeds demo data when `PANIC_ENV=prod` (`PANIC_SEED_ON_START` defaults to `never`
  there).

## 2026-11-14 — List reordering only in the Edit List dialog
- Removed drag-to-reorder rows from list cards on dashboards and on `/lists`; item order now changes only in
  the Edit List dialog.
- Removed the `/api/v1/lists` `action: "reorder"` endpoint.

## 2026-11-14 — JIT entitlements removed
- Removed live JIT entitlement providers: `/api/v1/entitlements`, `.rdp` entitlement gating,
  `ENTITLEMENT_DENIED`, and all `PANIC_JIT_*` / `PANIC_ENTITLEMENT_*` settings.

## 2026-11-14 — Operations documentation and end-to-end tests
- `DEPLOYMENT.md` (single node, HA, Docker Compose, reverse proxy and `X-Forwarded-For`, authentication
  rollout, backup and restore, Prometheus, upgrades) and `CONFIGURATION.md` (every `PANIC_*` / `*_FILE`
  variable).
- End-to-end tests for sessions, CSRF, persistence, audit, export, proxy-resolved zones and spoofing,
  multi-user access control, View As, default dashboards, launchers, and documentation coverage of settings.
- The container image sets `DJANGO_SETTINGS_MODULE`, so `docker compose exec server python -m django …` works.

## 2026-11-14 — Live JIT entitlement providers
- `static`, `ldap` (group membership) and `rest` (policy decision point) providers with per-item rules,
  a TTL cache, timeouts, and `WARN` / `BLOCK` gates. Provider errors show "Entitlement Check Unavailable";
  `PANIC_ENTITLEMENT_FAIL_CLOSED` enforces `BLOCK` gates during outages.
- `GET /api/v1/entitlements`; `.rdp` launches enforce `BLOCK` gates (`403 ENTITLEMENT_DENIED`, audited).
  Disabled by default. (Removed later the same day.)

## 2026-11-14 — Production container and compose stack
- Container runs as unprivileged `panic:panic` (uid/gid 10001), with a `/data` volume, a `HEALTHCHECK` on
  `/api/v1/health` and PostgreSQL support.
- Entrypoint: migrations (`PANIC_MIGRATE_ON_START`), seeding (`PANIC_SEED_ON_START=if-empty|never`),
  gunicorn tuned by `PANIC_GUNICORN_WORKERS` / `THREADS` / `TIMEOUT`.
- `compose.yaml`: read-only root filesystem, named volumes, full `PANIC_*` pass-through, optional
  PostgreSQL 17 profile.
- Fixes: `manage.py migrate` / `panic_seed` no longer fail with a circular import; rate-limit windows start
  at the client's first request.

## 2026-11-14 — CSRF, security headers, rate limiting, audit filtering
- CSRF enforced on every state-changing request; API CSRF failures return `403 CSRF_FAILED`.
- Security headers: `Content-Security-Policy` (override with `PANIC_CSP`), `X-Content-Type-Options`,
  `Referrer-Policy: same-origin`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`. Optional
  `PANIC_SECURE_SSL_REDIRECT`, `PANIC_HSTS_SECONDS`, `PANIC_SECURE_PROXY_SSL_HEADER`.
- Per-client-IP rate limits (`PANIC_RATE_LIMIT_LOGIN=10/60`, `PANIC_RATE_LIMIT_API=300/60`; `429
  RATE_LIMITED` with `Retry-After`).
- Audit filtering by actor, action, target type and text, with a filter bar on `/audit`.

## 2026-11-14 — Session authentication, OIDC and LDAP
- Session sign-in: unauthenticated pages redirect to `/login`, API calls return `401 UNAUTHENTICATED`.
- Local bootstrap admin (`PANIC_BOOTSTRAP_ADMIN_USER` / `_PASSWORD[_FILE]`), login page, CSRF-protected
  logout, open-redirect-safe `next`, and `auth.login` / `auth.login_failed` / `auth.logout` audit events.
- OIDC Authorization Code + PKCE (state, nonce, issuer, audience and expiry checks; issuer discovery;
  userinfo) and LDAP / LDAPS / StartTLS bind (RFC 4515 filter escaping). External sign-ins provision users
  automatically.

## 2026-11-14 — Database storage, export and import
- `/api/v1/health` reports database connectivity (`503` when degraded).
- `manage.py panic_export [--output FILE] [--shared-only]`, `manage.py panic_import FILE [--replace]` and
  `GET /api/v1/export` (Global Admin). Versioned JSON (`format: panic-export`, `schema_version: 1`), secrets
  excluded.

## 2026-11-14 — Persistence and trusted proxy
- SQLite (default) or PostgreSQL storage, idempotent `manage.py panic_seed` (`--if-empty`, `--reset`) and
  a write-through audit log.
- Client IP taken from the right-most untrusted `X-Forwarded-For` / `X-Real-IP` hop, honoured only from
  `PANIC_TRUSTED_PROXY_CIDRS`; responses carry `X-Client-IP` and `X-Security-Zone`.

## 2026-11-14 — Initial release (v0.1.0)
- `./panic` control script, environment configuration loader and structured JSON logging with request ids.
- Domain model with protocol-aware target normalisation and deduplication, credential hygiene validation,
  IPv4/IPv6 longest-prefix Security Zone resolution, access control and same-scope list validation, and
  sanitised `.rdp` / CLI template interpolation.
- Dark-first operations UI with bookmarkable URLs (`/dashboard/<id>`, `/dashboard/<id>/edit`, `/catalog`,
  `/lists`, `/sites`, `/teams`, `/zones`, `/rbac`, `/settings`, `/profile`, `/audit`), a 12-column
  full-width dashboard grid (`HOST` and `LIST` widgets), user and app-wide default dashboards, Command
  Palette (`Ctrl+K`) and admin View As.

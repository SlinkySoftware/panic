# Changelog

## 2026-11-15 — T-S6-12 done: CI green on gitea
- The joint smoke test failed in CI only: the job runs in a container but `docker run -v` is resolved by the
  host daemon, so a `/tmp` work dir mounted as an empty root-owned folder. It now lives in the checkout
  (the runner's `bind_workdir`). Run 697: checks and images green; `panic-web` and `panic-server` published.

## 2026-11-15 — Density setting removed; always compact
- Removed the top-bar density toggle and the Density field on User Settings: it was stored but never
  changed the layout. The UI is compact. The server keeps the stored `density` pref (unused), default
  now `COMPACT`.

## 2026-11-15 — View As a user and/or a zone
- `PUT /admin/view-as` takes `user_id` and/or `zone_id` (at least one). A zone overrides the IP-derived
  zone for reachability (`client.zone_source: VIEW_AS`); no user means the admin's own perspective from
  that zone. Mutations stay refused while any View As is active; exit clears both. AR-2.9 updated.
- Web: the View As prompt (raw user id) is now a dialog with a user search and a zone picker; the banner
  shows the zone.

## 2026-11-15 — Zone specificity, example data commands, menu names
- Zone resolution: longest prefix wins; on a tie the zone with the smallest total address space wins
  (a zone that is just this /22 beats one spanning several networks), then higher `priority`, then name.
  The Zones page hint ("Lower wins") was wrong: priority is a tie-breaker and higher wins.
- `./panic addexamples` / `delexamples` (`manage.py panic_examples add|remove`): a dedicated example dataset (5 sites, 5 teams, 4 zones, 20 users, 120 items incl. 25 routers, 15 firewalls, 20 switches, vCenter/ESXi/NSX/vRA; 23 lists, 7 dashboards), formerly a re-keyed copy of the demo
  profile (ids `example-*`, users `ex-*` without passwords, codes `EX-*`, documentation-only CIDRs), added
  next to existing data and idempotent; removal deletes only those and strips references real data picked up
  (list items, dashboard widgets, team/zone ids, menu pins and defaults), keeping sites real items still use.
- Menu: "Settings" is now "Application Settings", "Profile" is "User Settings".

## 2026-11-15 — `./panic promote|demote <username>`
- New `manage.py panic_user_admin promote|demote <username>` (via `admin_service.update_user`: the last
  enabled Global Admin cannot be demoted; audited as `cli:<os user>`), exposed as `./panic promote|demote`
  and `./panic user promote|demote`. `./panic manage` now loads `.env` like `start`.

## 2026-11-15 — T-S6-14: load test
- `Build/LoadTest/` (`run.sh`, `locustfile.py`, `mint_sessions.py`; `uv sync --group loadtest`): built
  images, 1 web + 2 servers, the shared dev Mongo in its own `panic_loadtest` database, 50 real sessions
  over 4 zones, 15 min steady state plus a stress run. Results and follow-ups in
  `Documents/Operations/PERFORMANCE.md`: 0 errors; all p95 targets met except search (140 ms vs 100) and
  catalog page (130 ms vs 120); saturation about 142 req/s, MongoDB-bound.
- Fix: `panic_seed` now gives seeded resources `search_keys` (seeded data was unsearchable).
- `./panic` dev-tools sync uses `uv sync --inexact`, so it no longer uninstalls the loadtest group.

## 2026-11-15 — Per-user SSH URI handler (one click into PuTTY / OpenSSH)
- Settings (Global Admin): "SSH system handler" switch and scheme (default `panic-ssh`). Off removes the
  SSH `launch.uri` everywhere; on, it is `<scheme>://user@host:port` (was `ssh://`). Cached per process
  like zones. `PATCH /settings` takes any of the default dashboard and the two SSH fields.
- Profile: setup section (shown when enabled) with a client choice (PuTTY / OpenSSH), a one-line
  PowerShell install command and a remove command. It writes `%LOCALAPPDATA%\PANIC\panic-ssh.ps1` and
  registers the scheme under `HKCU\Software\Classes` (no admin). The URL reaches the script only as a
  `-File` argument and is validated (`user@host:port`, no leading `-`, no quotes or spaces) before
  `Start-Process`; Constrained-Language-safe. Verified in a PowerShell container: valid links build the
  right PuTTY / ssh command, injection and option-smuggling links exit 2.

## 2026-11-15 — SSH client presets; full name in the header
- Profile: "SSH client" dropdown (OpenSSH, PuTTY, Plink, Windows Terminal + OpenSSH, Custom) filling the
  editable template; editing makes it Custom; live preview. Presets are client-side
  (`components/profile/sshPresets.ts`, unit-tested); the server's template hygiene accepts all of them.
- Header: "Portal for Accessing Networks, Infrastructure, and Compute" under the PANIC title.

## 2026-11-15 — Dashboard icons in the menu
- Dashboards carry an `icon` (Material icon name, default `dashboard`, validated server-side), set on
  create (`POST /dashboards`) and in edit mode's Dashboard details (`PATCH`), returned in
  `ui/bootstrap` `nav.dashboards`, dashboard summaries and views. The left menu and the Add dashboard
  list show it. `IconPicker.vue`: curated operations icons with search, or any valid icon name.

## 2026-11-15 — T-S6-13: operations and user documentation
- `CONFIGURATION.md`: container init, gunicorn, panic-web, compose/dev variables and a "Removed in
  Stage 6" table; the coverage test now scans all server modules, both images and the compose files,
  and fails if a removed variable is read again.
- `DEPLOYMENT.md` rewritten for Stage 6: topology, compose, replicas and migrations, a four-tier
  trusted-proxy worked example (incl. the L4 LB caveat), MongoDB URI and least-privilege role,
  `mongodump` and `panic_export` backups, monitoring, upgrades, dev workflow.
- `UI_DESIGN.md` §4 (Quasar mapping), `README.md` and `SESSION_STATUS.md` updated.

## 2026-11-15 — T-S6-12: containers, compose, CI with two images (verified locally; CI run pending push)
- `panic-web` image: Node build stage, then `nginx-unprivileged` 1.29 on 8080 (read-only root fs works:
  the template renders into `/tmp`). `Build/scripts/gen_nginx_conf.py` (+ tests) generates the server
  block from `proxy-paths.json`: allow-listed paths only, `/metrics` and other API paths 404, security
  headers and CSP, gzip, immutable `/assets/`, SPA fallback, `/healthz`. `10-panic-server-url.envsh`
  validates `PANIC_SERVER_URL` (bare origin; `_FILE` supported via `common/panic-env.sh`).
- `panic-server` image: API only (no static), `gthread` with `preload_app=False`
  (`panic_server/gunicorn_conf.py`), init step (`panic_ensure_indexes`, `panic_migrate` when
  `PANIC_MIGRATE_ON_START`), `HEALTHCHECK` on `?ready=1` sending a Host that `PANIC_ALLOWED_HOSTS` accepts.
- `compose.yaml` (web, server with `PANIC_SERVER_REPLICAS`, `demo-mongo` profile),
  `compose.standalone.web.yaml`, `compose.standalone.server.yaml`.
- CI: `Build/ci/mongo_service.sh`, `contract_checks.sh`, `container_smoke.sh` (two server replicas
  behind web; sign-in, allow-list, `FIRST_UNTRUSTED_HOP` client IP, cross-replica and post-restart
  sessions) and a rewritten `.gitea/workflows/ci.yaml` publishing both images. `./panic test` uses an
  externally supplied `PANIC_TEST_MONGO_URI` and runs `Build/scripts/tests`.
- Test fix: the LDAP filter-escaping test pins `PANIC_LDAP_USER_FILTER` so a developer `.env` cannot leak in.

## 2026-11-15 — T-S6-11 done (and T-S6-10 done): admin and user screens
- `/zones` (CIDR chips, priority, built-in Default zone description-only, Test IP), `/settings/users`
  (search; permission, team and status filters; pre-provision; disable / enable), `/settings/users/<id>`
  (display name, permissions, team membership, enable, View As, owned counts), Teams members dialog
  (read-only, linked to users), `/settings/orphans` (assign to an enabled user, delete), `/settings`
  (app-wide default dashboard, export, admin links), `/profile`, `/audit` (filters in the URL, keyset
  "Load more"), `/settings/client-ip` (summary, hop table, policy, raw headers).
- Catalog cards gain zone and (shared card) team filters.
- First component tests (`test/unit/adminForms.spec.ts`): validation display and server field errors.

## 2026-11-15 — T-S6-09 (part 3): Command Palette — T-S6-09 done
- Ctrl/Cmd+K, `/` outside text fields, or the top-bar Search button: debounced `/ui/search`, arrow keys,
  Enter launches an item from its `launch` or opens a dashboard / list. Shortcut handling unit-tested.
- Not done from the T-S6-09 acceptance: the manual payload-budget check against the loadtest dataset.

## 2026-11-15 — T-S6-09 (part 2): dashboard edit mode
- `/dashboard/<id>/edit`: 12-column grid editor (drag header to move, corner to resize, overlaps pushed down;
  `components/dashboard/grid.ts` mirrors the server clamp, with unit tests), Add Widget (HOST / LIST pickers
  that skip targets already on the dashboard), widget properties, dashboard details and delete, Save with
  `If-Match` and a conflict banner (discard / overwrite), unsaved-changes guard.
- Server: `PUT /dashboards/{id}/layout` rejects the same item or list twice (`400 VALIDATION_ERROR`).
- Nav rail can be pinned open (remembered per browser).

## 2026-11-15 — T-S6-09 (part 1): dashboard view, launch, add-dashboard menu
- `/dashboard/<id>` locked view: HOST and LIST widgets on a 12-column CSS grid, launch actions (open URL,
  copy command, `.rdp` download, optional system URI), DIM of unreachable items, placeholders for unavailable
  targets, "Show all (N)" to `/lists?open=<id>`, ETag / `If-None-Match` revalidation, pin/unpin and
  set/reset my default.
- Menu "Add dashboard": pin an existing visible dashboard not yet in the menu, or create a new one.
- `./panic`: the web dev server always allows this machine's hostname and FQDN; `PANIC_WEB_ALLOWED_HOSTS`
  only adds extras.

## 2026-11-15 — T-S6-10 / T-S6-11 (part): Sites, Teams, Catalog and Lists screens
- Sites and Teams admin tables (`components/admin/CodeNamedTable.vue`, one component, reloads on route
  change): search, create, edit, delete; write actions for Global Admins only.
- `/catalog`: Global & Team and Personal cards, server-paged with search and protocol/site filters and a
  Teams column on the shared card; protocol-aware item modal with live preview, hygiene and field errors,
  and a duplicate prompt that resends with `force_allow_duplicate`. Catalog list rows now carry `team_ids`.
- `/lists`: same two cards; Edit List modal with a same-scope item picker, drag or arrow reordering, and
  `If-Match` saves with a conflict banner; read-only for non-editors; `?open=<id>` opens a list.
- Fixes: `newRequestId` falls back to `getRandomValues` outside secure contexts (plain-HTTP dev access by
  hostname); the Vite dev server takes extra allowed hostnames from `PANIC_WEB_ALLOWED_HOSTS`.

## 2026-11-15 — T-S6-08: panic-web foundation — Vue 3 + Quasar + TypeScript scaffold, auth, shell, nav
- New `Application/Web` SPA: every AR-1.4 URL routed (login + shell built; everything else a
  placeholder pending `T-S6-09`/`10`/`11`), a login page (local/LDAP form + OIDC button, driven by
  `GET /api/v1/auth/providers`), a bootstrap-driven nav rail (dashboard pins/★ default/📌 locked),
  top bar (zone badge, View As banner/switcher, density/theme toggles persisted to
  `LocalStorage`). `src/api/http.ts`: CSRF header with exactly one retry, `401` →
  `/login?next=...`. `src/api/generated/openapi.ts` generated from the committed OpenAPI document
  (`npm run gen:api`, with a drift-check unit test) via `openapi-fetch`/`openapi-typescript`.
  `dev-proxy.ts` + `proxy-paths.json` are the one allow-list (API.md §9, AR-6.4), with a unit test
  checking the dev proxy actually honours it.
- `panic` script: pins Node into `.tools/` (checksum-verified download), `start`/`stop`/`status`
  now manage two components (`server` on 8121, `web` on 8120 — the dev port swap this task's scope
  called for), `test` gained a `web` mode (lint/typecheck/vitest) wired into `all`.
- **Deviations:** found and fixed real bugs surfaced while actually running this for the first
  time (not just unit tests) — a block comment in `dev-proxy.ts` embedded a literal `*/` inside
  the regex it was documenting, prematurely closing the comment and breaking the Quasar/Vite
  build entirely; `refreshCsrfToken()` called the global `fetch` with a bare string URL instead of
  a `Request`, inconsistent with every other call site and every test mock that assumes `.url` is
  readable off the first argument; `test/unit/guard.spec.ts` lacked the Pinia + fetch-stub setup
  its sibling test files already use, needed because a redirect to `/` always cascades through
  `/`'s own `beforeEnter` (`toDefaultDashboard`), which uses the real session store regardless of
  the fake one handed to `authGuard` directly; six `vi.fn(async ...)` test mocks never awaited
  anything (`@typescript-eslint/require-await`). Also dropped the raw dashboard UUID
  `PlaceholderPage.vue` showed under its title — UUIDs are an internal identifier and belong only
  in the URL, never in user-facing text (owner feedback).
- Verified live, not just via unit tests: `./panic start` serves the SPA at `:8120`, sign-in
  (`GET /auth/csrf` → `POST /auth/login` → `GET /ui/bootstrap`) works end-to-end through the dev
  proxy against the real running server.
- `./panic test`: 222 Python + 64 web tests passed; ruff/mypy/import-linter and web
  lint/typecheck both clean.
- The npm-mirror environment blocker noted below (now resolved) is why this task's completion
  came after, not alongside, the standalone migrate-command fix.

## 2026-11-15 — Fix: `./panic start` used a relational `migrate` command that no longer exists
- `cmd_start` in the `panic` script still ran `manage.py migrate --noinput` before serving.
  `T-S6-04` removed `DATABASES` entirely (Mongo-only since then), so this has silently crashed
  `./panic start` on `main` since that commit. Replaced with `manage.py panic_ensure_indexes` +
  `manage.py panic_migrate` (the Mongo-era equivalents, `T-S6-02`). Verified live: clean start,
  `/api/v1/health`/`/api/v1/auth/providers` respond, `./panic test` still 222/222.
- **Deviation note:** `Build/Containers/server/entrypoint.sh` has the identical stale
  `manage.py migrate` call — left untouched since it's owned by the not-yet-run `T-S6-12`, which
  must fix it too (see `Documents/SESSION_STATUS.md`).
- Found while implementing `T-S6-08`, which was blocked at the time on an unrelated environment
  issue (resolved; see `Documents/SESSION_STATUS.md`) and not committed with this fix.

## 2026-11-15 — T-S6-07: Scoped API part 2 — resources, mutations, concurrency, admin, diagnostics
- Built the rest of the API.md §4.3–§4.7 surface: `/me`, catalog/lists/dashboards CRUD (`If-Match`
  required on dashboards and lists, `428`/`409 VERSION_CONFLICT` with `current_version`),
  admin (sites/teams/zones/users/orphans/view-as/settings), audit, export, and
  `GET /api/v1/admin/client-ip` diagnostics. New `services/{dashboards,catalog,lists,admin,
  profile,audit,view_as}.py`, `api/concurrency.py` (If-Match parsing/428/409 shaping),
  `api/validation.py`.
- Closed F1–F6 (ADR-0001): F1 user-permission/team mutations and audit (F2) are
  `GLOBAL_ADMIN`-only; duplicate-catalog and `zones/test-ip` (F5) report only what the caller can
  see; list saves (F6) reject invisible or wrong-scope item ids without mutating; edit/delete
  (F4) enforce ownership/team membership via `panic_common.visibility.matches`/`can_edit`
  exclusively (never the older `rbac.is_visible_in_scope`, which DATA_MODEL.md §5 keeps only as
  the parity-test baseline). Orphan lifecycle (team delete -> orphan -> admin-only visible,
  `403 ORPHANED_RESOURCE` on edit, assign-to-user, admin-only delete) and default-zone/last-site/
  last-admin/app-wide-default protected-resource rules all have regression tests. A real
  2-thread concurrent-edit test confirms exactly one winner.
- **Deviations:** found and fixed a real bug in `auth/middleware.py` (View As was popping its own
  session key on the request that started it, reading a stale `context` snapshot) and a round-trip
  gap in `panic_common.models` (`UserAccount.last_login_at`, `AuditLogEntry.{view_as_username,
  client_ip,zone_id,request_id}` were written but silently dropped on read). Both narrow,
  necessary fixes to already-merged files, not design changes. New `ReadAuthenticatedWriteAdmin`/
  `IsRealGlobalAdmin` permission classes for routes where `GET` is any-signed-in-user but the
  write is admin-only (sites/teams/zones/settings), and for View-As exit needing the *real* user.
- `./panic test`: 222 passed; ruff, mypy, import-linter (AR-1.1/4.1/4.2) clean.
  `./panic contracts --check`: clean.

## 2026-11-15 — T-S6-06: Scoped API part 1 — DRF scaffold, auth, UI read endpoints, OpenAPI
- New `panic_server.api` package: error envelope (`api/errors.py`, every DRF/domain exception ->
  API.md §3 shape), `RequestContextAuthentication` (bridges T-S6-04's `request.context` into
  DRF's `request.user`/CSRF enforcement), three closed permission tiers
  (`IsPublic`/`IsAuthenticated`/`IsGlobalAdmin`, deny-by-default, AR-2.8), weak-ETag/304 helper,
  and page/keyset pagination infra (built now, wired up by `T-S6-07`).
- 8 new endpoints: `GET/POST /api/v1/auth/{providers,csrf,login,logout}`,
  `GET /api/v1/ui/{bootstrap,dashboards/{id},search}`, `GET /api/v1/launch/rdp/{id}.rdp` — backed
  by new `services/{bootstrap,dashboards_read,search,launch}.py` composition layers over
  `panic_server.store`. `ItemView`/launch-command interpolation reuses
  `panic_common.{launchers,zones.check_item_reachability}`.
- `drf-spectacular` wired in (`SPECTACULAR_SETTINGS`, `--validate --fail-on-warn`); new
  `./panic contracts [--check]` regenerates/diffs `Documents/Architecture/openapi/server.yaml`.
- **Deviations:** cut the old `/login`/`/logout` JSON stopgap over to the real
  `/api/v1/auth/login`/`logout` per API.md §4.1/§5 (T-S6-04's own report flagged this as deferred
  here) — OIDC routes untouched. Small follow-up fixes to already-merged files: `security.py`'s
  rate-limit bucket now matches `/api/v1/auth/login` (and fixed a real bug: `_login_username` read
  `request.POST` before `.body`, 500ing on non-form POSTs); `health_view` now actually honors
  `?ready=1` instead of always pinging Mongo; added narrow `get_catalog_items_by_ids`/
  `get_lists_by_ids` batch-fetch repo functions (needed to meet the dashboard-view Mongo
  round-trip budget, API.md §8); `panic_common.visibility.Scoped`'s attributes became read-only
  `@property` declarations (a real mypy covariance gap the first production caller surfaced — no
  runtime behaviour change).
- `./panic test`: 190 passed; ruff, mypy, import-linter (AR-1.1/4.1/4.2) clean.
  `./panic contracts --check`: clean.

## 2026-11-14 — T-S6-04: Stateless request context, removal of simulator / SQL / snapshot store
- New `panic_server.context.RequestContext` (frozen dataclass; `build_request_context(request)`):
  real user, effective user, View As flag, client IP, `ChainResolution` and resolved zone —
  resolved fresh per request from the request's own session/headers, no process globals or lock.
  `middleware.RequestContextMiddleware` (renamed from `ClientIpZoneMiddleware`) builds it and
  enforces `PANIC_UNTRUSTED_PEER_POLICY=reject` (403 `UNTRUSTED_PEER`, loopback health/version
  exempt, AR-5.3 point 3) — the cutover from the old `resolve_client_ip` to T-S6-05's
  `resolve_client_chain` that T-S6-05 deferred to this task.
- Sessions switched to `panic_server.store.sessions.SessionStore` (AR-4.7); rate limiting moved
  to Mongo (`login:ip`/`login:user`/`api:ip` fixed-window buckets via `store.rate_limits`).
  Auth backends (local/OIDC/LDAP) ported to `store.repos.users`; external sign-in no longer maps
  IdP groups to permissions/teams (`panic_common.claim_mapping` deleted, decision 11): first
  sign-in gets no permissions/teams, later sign-ins only update `display_name`/`last_login_at`.
  Disabled users cannot sign in and their sessions are rejected.
- Deleted the entire Stage 1-4 SQL/simulator stack: `state.py`, `store_db.py`, `models.py`,
  `migrations/`, the old `portability.py`, `templates/`, `static/`, `SimulationState`, and every
  STORE-coupled view (the server-rendered UI shell and the whole `/api/v1/*` CRUD surface for
  dashboards/catalog/lists/sites/teams/zones/rbac/audit/export/the `.rdp` launcher) — rebuilt
  against the new DRF/Mongo stack by `T-S6-06`/`T-S6-07`. `views.py`/`urls.py` now carry only
  health (Mongo-ping-backed)/version/metrics plus auth. Removed ~20 settings (`PANIC_DB_*`,
  `PANIC_AUTO_SEED`, `PANIC_AUTH_MODE`, `PANIC_DEV_SIMULATOR_ENABLED`, `PANIC_CACHE_URL`,
  `PANIC_STATIC_ROOT`/`SERVE_STATIC`, `PANIC_RBAC_*`, OIDC groups claim, LDAP group search);
  added `PANIC_UNTRUSTED_PEER_POLICY`/`PANIC_XFF_MAX_HOPS`/`PANIC_XFF_MAX_BYTES`. `DATABASES` and
  `django.contrib.sessions`/`staticfiles` dropped from `INSTALLED_APPS` entirely (nothing needs
  them). AR-4.2 (no Django ORM) added and green alongside AR-1.1/AR-4.1.
- **Transition (expected, per task spec):** the old `panic.js` UI no longer works on `main`.
  `main` has no working interactive UI until the web rewrite (`T-S6-08`-`T-S6-11`) lands.
- **Deviation:** kept the `X-Client-IP`/`X-Security-Zone` response headers rather than removing
  them (ARCHITECTURE.md's aspirational note that S6 drops them in favour of the access log) —
  harmless, backward-compatible, and the admin diagnostics endpoint that formally replaces them
  is a later task. AR-4.2's import-linter contract needed `"django"` added to `root_packages`
  (a `forbidden` contract can't target a dotted path inside an external package otherwise) and
  `allow_indirect_imports = true` (Django's own internals transitively touch `django.db.models`
  from nearly everywhere; only *direct* imports in `panic_server` should trip the contract).
- `./panic test`: 161 passed; ruff, mypy, import-linter (AR-1.1/AR-4.1/AR-4.2 all kept) clean.
  Acceptance grep for `STORE`/`MockPortalStore`/`SimulationState`/`simulator` across
  `Application/` finds only historical comments explaining the removal, no live references.

## 2026-11-14 — T-S6-03: Seed, export and import on Mongo
- New `panic_server.fixtures` (`demo`: a small hand-built dataset; `loadtest`: a deterministic,
  index-derived generator producing exactly 5,000 catalog items / 50 users / 12 teams / 20 zones
  / 200 lists / 60 dashboards, RFC 5737/3849/`example.com` only) and `panic_server.services.portability`
  (`schema_version: 2`, built only on `panic_server.store.repos.*`, sections sorted by `id` for
  byte-stable round-trips).
- `panic_seed`/`panic_export`/`panic_import` management commands rewritten to be Mongo/v2-only
  (same CLI shape as before: `--profile demo|loadtest`, `--reset`/`--if-empty`, `--output`/
  `--shared-only`, `--replace`), reaching Mongo only through `panic_server.store` (AR-4.1 green).
  Added small, additive `upsert_<x>`/`delete_all_<x>`/`list_all_<x>` primitives to the T-S6-02
  repos where portability needed them.
- **Deviation:** `test_store_db.py::test_panic_seed_is_idempotent` and
  `test_server.py::test_export_then_import_on_clean_database_reproduces_state` pinned the old
  SQL/v1 CLI behaviour this task replaces, so they were deleted; equivalent (and broader) coverage
  now lives in the new `tests/test_portability.py`. The old SQL-backed `panic_server/portability.py`,
  `views.py`'s `/api/v1/export`, `state.py` and `store_db.py` are untouched (reserved for `T-S6-04`).
- `./panic test`: 197 passed; ruff, mypy, import-linter (AR-4.1 kept) all clean.

## 2026-11-14 — T-S6-02: MongoDB repository layer, indexes, sessions, rate limits
- New `panic_server.store` package (the only importer of `pymongo`/`bson`, AR-4.1): lazy
  per-process client, named `IndexSpec`-based `ensure_indexes` (idempotent, conflict detection,
  TTL `collMod`), `visibility_filter` (Mongo `$or`, parity-tested against
  `panic_common.rbac.is_visible_in_scope` on ~2,000 generated documents), CAS `version` writes
  with domain `NotFound`/`VersionConflict`/`DuplicateKey` exceptions, repos for sites/teams/
  zones/users/catalog/lists/dashboards/settings/audit/orphans, a Mongo-backed `SessionStore`
  (AR-4.7: primary reads, `w=majority` writes, cross-process continuity) and fixed-window
  `rate_limits.increment`. `panic_migrate` step 1 creates the Default zone and `system` settings
  doc idempotently.
- New local dev Mongo container `panic-dev-mongo` (`Build/Containers/compose.dev-mongo.yaml`,
  host port 27117), started/reused by `./panic start` and `./panic test`.
- **Deviation:** `SessionStore` and `rate_limits.increment` are built and unit-tested but not
  wired into `settings.SESSION_ENGINE` / `security.RateLimitMiddleware` — those files are owned
  by `T-S6-04`, which does the stateless cutover. The visibility-parity fixture's PERSONAL-orphan
  case is narrowed to "no owner at all" (not "all owners disabled"), since
  `is_visible_in_scope` — the function DATA_MODEL §5 pins the parity test to — has no
  admin-sees-all-orphans bypass for that PERSONAL sub-case; see the comment in
  `test_filters_visibility_parity.py`.
- `./panic test`: 188 passed; ruff, mypy, import-linter (AR-4.1 kept) all clean.

## 2026-11-14 — Process change: no long-lived Stage 6 branch
- Owner decision: every task now works in its own fresh, short-lived worktree and pushes straight
  to `main` on both `origin` and `gitea` (fast-forward), instead of accumulating on a `stage6`
  branch merged only at milestones. This keeps a new session's fresh worktree always clean off
  `main`, with no stale branch or worktree to track.
- `T-S6-01` and `T-S6-05` (developed on the now-deleted `stage6` branch) are merged into `main` as
  part of this change.
- `PHASE_B_KICKOFF.md` and `TASKS.md`'s coordination rules are updated accordingly. `./panic test`
  must still stay green on every commit to `main`; a fully working interactive app between tasks
  is not guaranteed pre-release (e.g. the old UI stops working on `main` after `T-S6-04` until the
  web rewrite lands).

## 2026-11-14 — T-S6-05: hardened X-Forwarded-For / Forwarded chain resolution
- `panic_common.proxy.resolve_client_chain` (pure, additive — the Stage 3 `resolve_client_ip`
  stays for now since `middleware.py` still calls it until `T-S6-04`): walks the hop chain right
  to left per AR-5.3, returning a `ChainResolution` (hops, `ignored_left_hops`, `truncated`,
  `decision`, `client_ip`, `location_known`) matching the API.md §6 `client-ip` diagnostics shape.
- Parses RFC 7239 `Forwarded` (`for=`, quoted/bracketed IPv6, ports, obfuscated identifiers) as
  well as `X-Forwarded-For`; normalises IPv4-mapped IPv6; honours `max_hops`/`max_bytes` with a
  `truncated` flag.
- Every unknown-location decision (`UNTRUSTED_PEER`, `NO_HEADER`, `ALL_HOPS_TRUSTED`,
  `MALFORMED_HOP`) is flagged `location_known=False`. `untrusted_peer_policy` is carried on
  `ProxyChainConfig` for the caller; this pure function never raises or rejects.
- 43 table-driven cases in `test_proxy.py` (AR-5.5): four-tier chains, left-hand client spoofing,
  an untrusted-peer spoof attempt, a jump host inside an overly broad trusted CIDR (documented
  pitfall), repeated/joined header lines, IPv4-mapped IPv6, bracketed/ported IPv6, `Forwarded`
  parsing, `unknown`/junk/obfuscated tokens, and `max_hops`/`max_bytes` truncation.

## 2026-11-14 — T-S6-01: pure domain rules for scoped access
- `panic_common.visibility` (new): `VisibilitySpec`/`visibility_spec`, `matches` (mirrors the Mongo
  `$or`), `can_create`/`can_edit` returning a `Decision` with an `ErrorCode`, `is_orphan`,
  `assign_orphan_to_user`, and the `zone-default` constants.
- `panic_common.search_keys` (new): the lower-cased, non-alphanumeric-split tokeniser (DATA_MODEL §4.10).
- New `ErrorCode`s (`VERSION_CONFLICT`, `PRECONDITION_REQUIRED`, `PROTECTED_RESOURCE`,
  `VIEW_AS_READ_ONLY`, `ORPHANED_RESOURCE`, `UNTRUSTED_PEER`, `PAYLOAD_TOO_LARGE`, `DATABASE_UNAVAILABLE`).
- Models: `version`/`updated_at`(/`updated_by`) on sites, teams, zones, catalog items, lists,
  dashboards, settings; `auth_source`/`disabled` on users; `orphaned` on catalog items, lists,
  dashboards; `builtin` on zones; `search_keys` on catalog items, lists, dashboards, users.
- import-linter: AR-1.1 extended (pymongo, bson, httpx, ldap3, requests, socket, ssl); new AR-4.1
  (`panic_server` forbidden from `pymongo`/`bson`) — **T-S6-02 must add the `ignore_imports` for
  `panic_server.store.**` once that package exists** (an unmatched `ignore_imports` pattern fails
  import-linter today, so it can't be pre-added).
- **Deviation:** `SimulationState` and `TeamDefinition.members` are *not* removed yet — both are
  still read by `panic_server/state.py`, `store_db.py`, `auth/backends.py`, `models.py`, `views.py`
  and `panic.js`, none of which T-S6-01 owns. Removing them now would break `./panic test` and the
  running dev server ahead of schedule. Deferred to `T-S6-04`, which owns and deletes those files.

## 2026-11-14 — Stage 6 design: identity, sessions and branching (docs only)
- External identity (OIDC, LDAP) is used for authentication only:
  - `panic_common.claim_mapping`, all `PANIC_RBAC_*` group mappings and `idp_permissions` are dropped from the plan.
  - Permissions and teams are set only on the users pages.
  - A first external sign-in creates a user with no permissions or teams.
- New rule AR-4.7, session continuity: a load balancer may move a user to any panic-web or panic-server instance or container without interrupting the session.
  - shared Mongo session store with primary reads and `w=majority` writes
  - identical secret key on every replica
  - OIDC state kept in the session, cookie-based CSRF
  - a shared public hostname or cookie domain
  - cross-replica tests and a two-replica CI smoke test
- Phase B runs on the `stage6` branch, `main` is updated only at milestones, and no interim working system is required.

## 2026-11-14 — Stage 6 design: owner review incorporated (docs only)
- ADR-0001 records the owner's answers.
- New decisions:
  - 10: orphaned resources are visible only to admins and read-only; the only actions are assign-to-user and delete.
  - 11: a users management page (`/settings/users`, `/settings/users/<id>`) is the only place team membership is set. `/rbac` redirects there, users are disabled rather than deleted, and IdP-mapped permissions are kept separate from manual grants.
  - 12: a built-in **Default** Security Zone for unknown client locations, replacing "unzoned".
- Also decided:
  - View As is read-only.
  - Admins cannot edit other users' `PERSONAL` resources.
  - There is no Stage 1–4 data migration or v1 import.
  - `PANIC_UNTRUSTED_PEER_POLICY` is now `default` (the default) or `reject`.
- `ARCHITECTURE.md`, `DATA_MODEL.md`, `API.md`, `SPEC.md` and `TASKS.md` are updated to match: new `orphaned`, `idp_permissions`, `disabled` and `builtin` fields; users and orphans endpoints; the `ORPHANED_RESOURCE` error; and `zone_source` in bootstrap and diagnostics.

## 2026-11-14 — Security hotfix: ADR-0001 findings F1–F3
- F1: `POST /api/v1/rbac` (`update_user`, `create_user`) now requires `GLOBAL_ADMIN` on the signed-in user. Before this fix, any user could grant themselves Global Admin.
- F2: `GET /api/v1/audit` is Global Admin only (otherwise `403`), and the portal snapshot's `audit_logs` is empty for non-admins.
- F3: `GET /api/v1/launch/rdp/<id>.rdp` returns `404` for items the effective user cannot see.
- Regression tests are in `Application/Server/tests/test_authz_hotfix.py`.

## 2026-11-14 — Stage 6 Phase A: design for the web/server split, MongoDB and scoped API (docs only)
- `Documents/Architecture/adr/0001-web-server-mongo-split.md`: the owner's decisions 1–9, the rejected alternatives, authorization findings F1–F6 in the current API, and open questions.
- `ARCHITECTURE.md` is rewritten for the Stage 6 target:
  - components panic-web, panic-server and Common
  - new rules AR-4.x (Mongo repository, statelessness, `version`/`If-Match`), AR-5.x (multi-tier `X-Forwarded-For` trust model, fail-closed) and AR-6.x (no full-state loading, payload budgets, committed OpenAPI, single proxy allow-list, layering)
  - import-linter contracts, including "only `panic_server.store` imports pymongo"
- `DATA_MODEL.md` describes:
  - MongoDB collections and document shapes, with indexes
  - `search_keys` prefix search
  - Mongo-backed sessions and rate limits
  - a 365-day audit TTL
  - the visibility filter spec and edit-rights table
- New `API.md`: the per-screen endpoint contract (bootstrap, dashboard view, search, paged catalog and lists, admin), error codes, ETag/If-Match semantics, client-IP diagnostics, payload budgets, and the panic-web proxy allow-list.
- `SPEC.md` gains Stage 6 and the deployment topology. It also records that the simulator is removed, the Command Palette search moves to the server, and list reordering happens only in the modal.
- `TASKS.md` gains Stage 6 (`T-S6-00` … `T-S6-14`) with owned files, dependencies, acceptance criteria and load-test p95 targets.

## 2026-11-14 — Gitea CI & image publishing
- `.gitea/workflows/ci.yaml`: `./panic test` + `makemigrations --check` on pushes / PRs to `main`; builds `Build/Containers/server/Containerfile`, smoke-tests it in prod mode (non-root, healthy, `/login`, static, `401` API), and publishes `panic-server` to the Gitea container registry for `main` (`:main`, `:sha-<short>`) and `vX.Y.Z` tags (`:X.Y.Z`, `:X.Y`, `:latest`) using `REGISTRY_USER` / `REGISTRY_TOKEN`.
- Container entrypoint no longer seeds demo fixtures when `PANIC_ENV=prod` (`PANIC_SEED_ON_START` defaults to `never` there); e2e test covers first sign-in on an empty database.

## 2026-11-14 — List reordering only in the Edit List modal
- Removed drag-to-reorder rows from Endpoint List cards on dashboards (LIST widgets) and on `/lists`; item order now changes only in the Edit List modal (saved with `action: "save"`).
- Removed the `/api/v1/lists` `action: "reorder"` endpoint. Static asset version bumped to `v=7`.

## 2026-11-14 — JIT entitlements removed from scope
- Removed live JIT entitlement providers (former Stage 5 / `T-S5-01`): `panic_common.entitlements`, `panic_server.entitlements_service`, `/api/v1/entitlements`, `.rdp` entitlement gating, `ENTITLEMENT_DENIED`, and all `PANIC_JIT_*` / `PANIC_ENTITLEMENT_*` settings. Stage 5 dropped from `SPEC.md` and `TASKS.md`.

## 2026-11-14 — T-S4-02: Operations Documentation & End-to-End Suite
- `Documents/Operations/DEPLOYMENT.md` (single-node SQLite, HA PostgreSQL, Docker Compose, reverse proxy / `X-Forwarded-For`, authentication rollout, `panic_export` / `panic_import` backup & restore, Prometheus, upgrades) and `Documents/Operations/CONFIGURATION.md` (every `PANIC_*` / `*_FILE` variable).
- `test_e2e_workflows.py`: session + CSRF + persistence + audit + export, proxy-resolved zone reachability and spoofing, multi-user RBAC with OIDC-provisioned users, Admin "View As", Default Dashboard precedence, list/widget persistence across reload, `.rdp` / SSH launchers, and a CONFIGURATION.md coverage guard.
- Container image sets `DJANGO_SETTINGS_MODULE` so `docker compose exec server python -m django …` works.

## 2026-11-14 — T-S5-01: Live JIT Entitlement Providers
- `panic_common.entitlements` (pure): `EntitlementProvider` protocol, thread-safe `TTLCache`, `EntitlementChecker` (concurrent checks bounded by `PANIC_ENTITLEMENT_TIMEOUT_S`, only definitive answers cached for `PANIC_ENTITLEMENT_CACHE_TTL_S`), `parse_rules`, and `WARN` / `BLOCK` `evaluate_gate`. Timeouts and provider errors yield `UNAVAILABLE` ("Entitlement Check Unavailable") instead of raising.
- `panic_server.entitlements_service`: `static`, `ldap` (group membership) and `rest` (HTTP policy decision point) providers; per-item rules from `PANIC_ENTITLEMENT_RULES[_FILE]`; `PANIC_ENTITLEMENT_FAIL_CLOSED` for `BLOCK` gates during outages.
- `GET /api/v1/entitlements[?refresh=1]` and `POST {"action":"refresh"}`; `.rdp` launches enforce `BLOCK` gates (`403 ENTITLEMENT_DENIED`, audited) and carry `X-PANIC-Entitlement-Warning` for soft gates / outages. Disabled by default (`PANIC_JIT_ENTITLEMENTS_ENABLED=false`).

## 2026-11-14 — T-S4-01: Production Container & Compose Stack
- `Containerfile`: unprivileged `panic:panic` (uid/gid 10001), `collectstatic` at build, `/data` volume (`PANIC_SQLITE_PATH=/data/panic.sqlite3`), `HEALTHCHECK` on `/api/v1/health`, installs the `postgres` extra (`psycopg[binary]`).
- `entrypoint.sh`: `migrate --noinput` (`PANIC_MIGRATE_ON_START`), `panic_seed --if-empty` (`PANIC_SEED_ON_START=if-empty|never`), Gunicorn tuned by `PANIC_GUNICORN_WORKERS/THREADS/TIMEOUT`.
- `STATIC_ROOT` (`PANIC_STATIC_ROOT`) with Django serving collected assets when `PANIC_SERVE_STATIC=true` and `DEBUG` is off.
- `compose.yaml`: read-only root FS, named volumes, full `PANIC_*` pass-through, optional `postgres` profile (PostgreSQL 17 with health-gated startup). `.dockerignore` added.
- Fix: `panic_server.state.STORE` is now built lazily (PEP 562) — `manage.py migrate` / `panic_seed` previously failed with a circular import when `store_db` was imported first.
- Fix: rate-limit windows start at the client's first request (removes a window-boundary race).

## 2026-11-14 — T-S3-04: CSRF, Security Headers, Rate Limiting & Audit Filtering
- `CsrfViewMiddleware` enforced on every state-changing request (all `@csrf_exempt` removed); `panic.js` `apiRequest` sends `X-CSRFToken` from the `panic_csrftoken` cookie / `<meta name="csrf-token">` and redirects to `/login` on `401`. API CSRF failures return `403 CSRF_FAILED` JSON.
- `SecurityHeadersMiddleware`: `Content-Security-Policy` (override with `PANIC_CSP`), `X-Content-Type-Options`, `Referrer-Policy: same-origin`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`. Optional `PANIC_SECURE_SSL_REDIRECT`, `PANIC_HSTS_SECONDS`, `PANIC_SECURE_PROXY_SSL_HEADER`.
- `RateLimitMiddleware`: per-client-IP fixed windows (`PANIC_RATE_LIMIT_LOGIN=10/60`, `PANIC_RATE_LIMIT_API=300/60`, `429 RATE_LIMITED` + `Retry-After`); counters in the Django cache (`PANIC_CACHE_URL` for shared Redis).
- `GET /api/v1/audit?actor=&action=&target_type=&q=&limit=` and a filter bar on `/audit` (filters reflected in the URL query string).

## 2026-11-14 — T-S3-01 / T-S3-02: Session Authentication, OIDC & LDAP
- `PANIC_AUTH_MODE=session`: `PanicAuthMiddleware` redirects to `/login` (HTML) or returns `401 UNAUTHENTICATED` (`/api/*`); session user bound to the store, Admin "View As" kept in the session. Simulator user switching / reset return `403` when `PANIC_DEV_SIMULATOR_ENABLED=false`.
- Local bootstrap admin (`PANIC_BOOTSTRAP_ADMIN_USER` / `_PASSWORD[_FILE]`, Django password hashing), reference-ui-styled `/login`, CSRF-protected `POST /logout`, open-redirect-safe `next`, `auth.login` / `auth.login_failed` / `auth.logout` audit events.
- `panic_common.claim_mapping` (pure): IdP groups (names or LDAP DNs) -> `PermissionFlag`s and Teams via `PANIC_RBAC_*_GROUPS`, `PANIC_RBAC_TEAM_GROUP_MAP`, `PANIC_RBAC_TEAM_GROUP_PREFIX`.
- OIDC Authorization Code + PKCE (`/auth/oidc/login`, `/auth/oidc/callback`; state, nonce, iss, aud, exp checks; issuer discovery; userinfo merge) and LDAP/LDAPS/StartTLS bind + group search (RFC 4515 filter escaping). External logins auto-provision users and sync permissions/teams. New dependencies: `httpx`, `ldap3`.

## 2026-11-14 — T-S2-03: API Cutover & Portable Export/Import
- `STORE` is a `DatabasePortalStore`; `PortalStoreMiddleware` refreshes relational state per request and persists changed entities afterwards (auto-seeds an empty database when `PANIC_AUTO_SEED=true`).
- `/api/v1/health` reports database connectivity (`503` when degraded); `/api/v1/version` reports stage 2.
- `manage.py panic_export [--output FILE] [--shared-only]`, `manage.py panic_import FILE [--replace]`, and `GET /api/v1/export` (`GLOBAL_ADMIN`). Versioned JSON (`format: panic-export`, `schema_version: 1`), secrets excluded.

## 2026-11-14 — Wave 1: Persistence Core & Trusted Proxy (T-S2-01, T-S2-02, T-S3-03)
- `PANIC_DB_ENGINE` (`sqlite` default at `.run/panic.sqlite3`, `postgresql` via `PANIC_DB_HOST/PORT/NAME/USER/PASSWORD[_FILE]/CONN_MAX_AGE`).
- Django ORM records (`panic_server.models`) with `to_domain()` / `from_domain()` round-trips to `panic_common.models`, indexes on `normalized_key`, `scope`, `created_at`, `dashboard_id`; initial migration `0001_initial`.
- `DatabasePortalStore` (`panic_server.store_db`): `MockPortalStore` contract with `refresh()` / baseline-diff `persist()` in a single transaction, explicit `save_*` / `delete_*` repository methods, write-through audit log with `query_audit()` filtering.
- Idempotent `manage.py panic_seed` (`--if-empty`, `--reset`).
- `panic_common.proxy.resolve_client_ip` (right-most untrusted `X-Forwarded-For` / `X-Real-IP` hop, only honoured from `PANIC_TRUSTED_PROXY_CIDRS`) and `ClientIpZoneMiddleware` (`request.client_ip`, `request.resolved_zone`, `X-Client-IP` / `X-Security-Zone` headers).

## 2026-11-14 — Initial Baseline (v0.1.0)
- Established `uv` workspace (`panic_common`, `panic_server`), `./panic` control script, environment configuration loader (`panic_server.conf`), structured JSON logging (`RequestIdMiddleware`), and `import-linter` boundary contract (`AR-1.1`).
- Implemented `panic_common` domain models, protocol-aware target normalization and deduplication, credential hygiene validation, IPv4/IPv6 longest-prefix Security Zone resolution, RBAC and same-scope list validation, and sanitized `.rdp` / CLI template interpolators.
- Built reference-ui-aligned dark-first operations UI with explicit bookmarkable URLs (`/dashboard/<dash-uuid>`, `/dashboard/<dash-uuid>/edit`, `/catalog`, `/lists`, `/sites`, `/teams`, `/zones`, `/rbac`, `/settings`, `/profile`, `/audit`), Zabbix-style 12-column full-width grid (`HOST` and `LIST` widgets), User Default and App-Wide Default Global Dashboard hierarchy, Command Palette (`Ctrl+K`), and Admin `"View As"` perspective switching.

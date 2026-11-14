# Changelog

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

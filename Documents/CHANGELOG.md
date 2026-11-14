# Changelog

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

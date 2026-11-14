# Changelog

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

# Changelog

## 2026-11-14 — Initial Baseline (v0.1.0)
- Established `uv` workspace (`panic_common`, `panic_server`), `./panic` control script, environment configuration loader (`panic_server.conf`), structured JSON logging (`RequestIdMiddleware`), and `import-linter` boundary contract (`AR-1.1`).
- Implemented `panic_common` domain models, protocol-aware target normalization and deduplication, credential hygiene validation, IPv4/IPv6 longest-prefix Security Zone resolution, RBAC and same-scope list validation, and sanitized `.rdp` / CLI template interpolators.
- Built reference-ui-aligned dark-first operations UI with explicit bookmarkable URLs (`/dashboard/<dash-uuid>`, `/dashboard/<dash-uuid>/edit`, `/catalog`, `/lists`, `/sites`, `/teams`, `/zones`, `/rbac`, `/settings`, `/profile`, `/audit`), Zabbix-style 12-column full-width grid (`HOST` and `LIST` widgets), User Default and App-Wide Default Global Dashboard hierarchy, Command Palette (`Ctrl+K`), and Admin `"View As"` perspective switching.

# PANIC — Enforced Architecture

> The rules here are **mandatory**. Code that violates them is a bug, even if it works.
> Rules are numbered (`AR-x.y`) so reviews and tests can cite them.

---

## 1. Components and boundaries

| Component | Path | Runtime | May talk to | Must never |
|---|---|---|---|---|
| **Server** | `Application/Server` | Django + Gunicorn (serves server-rendered HTML UI + `/api/v1/*` JSON + dynamic `.rdp` stream) | Relational DB (Stage 2+), Entitlement Providers (Stage 3) | Proxy interactive SSH/RDP terminal streams; store user passwords or private keys |
| **Common** | `Application/Common` | Python library `panic_common` (Pydantic v2 models, normalization, hygiene, CIDR resolution, RBAC & scope validation, `.rdp` & CLI template interpolation) | — (pure library, no I/O) | Import Django, database drivers, or network transport libraries |

- **AR-1.1** `panic_common` is a pure library with zero Django or I/O dependencies. Enforced via `import-linter`.
- **AR-1.2** PANIC is a **control plane and session launcher**, never an HTML5 session proxy. Session execution is handed off to native client tools (`ssh`, `putty.exe`, `mstsc.exe`, browser tabs, or local SOE binaries).
- **AR-1.3** Zero client modification required: all launch actions use standard browser tab navigation (`WEB`), clipboard command interpolation (`SSH`, `LOCAL_APP`), optional standard URI schemes (`ssh://`, custom URI), or dynamically streamed `.rdp` files (`Content-Type: application/x-rdp`).
- **AR-1.4** **Explicit, Bookmarkable UI URLs (No Hidden URLs):** Every screen and dashboard has an explicit server-rendered route (`urls.py`) and synchronized client-side History API URL (`panic.js`):
  - `/dashboard` (resolves to the user's effective Default Dashboard at `/dashboard/<dash-uuid>`)
  - `/dashboard/<dash-uuid>` (Locked View Mode) and `/dashboard/<dash-uuid>/edit` (Unlocked Edit Mode)
  - `/catalog`, `/lists`, `/sites`, `/teams`, `/zones`, `/rbac`, `/settings`, `/profile`, `/audit`.

## 2. Security, Hygiene, RBAC & Sanitization

- **AR-2.1** **Zero Credential Storage in Catalog/Cards:** `panic_common.hygiene.check_credential_hygiene` rejects any card or catalog submission containing embedded credentials (`user:pass@host`) or plaintext password flags (`-pw`, `--password`, `sshpass`).
- **AR-2.2** **Strict Launch Parameter Sanitization:** All values interpolated into `.rdp` files or CLI templates pass through `panic_common.launchers.sanitize_launch_param`, stripping `\r`, `\n`, NUL, and control characters (`0x00–0x1F`, `0x7F`) to prevent `.rdp` directive injection and shell/clipboard newline injection.
- **AR-2.3** **Ephemeral `.rdp` Generation:** `.rdp` payloads are generated in-memory per request and streamed with `Content-Type: application/x-rdp` and `Cache-Control: no-store`. They are never written to server disk.
- **AR-2.4** **Source IP & Security Zone Reachability Enforcement:**
  - Zone-level reachability (`All Zones` vs selected `SecurityZone` IDs resolved from client source IP against configured Zone CIDRs using longest-prefix match, then highest priority).
- **AR-2.5** **Unified Scope & Same-Scope List Enforcement:**
  - Catalog Items, Endpoint Lists, and Dashboards share `ScopeType` (`GLOBAL`, `TEAM`, `PERSONAL`).
  - Endpoint Lists strictly enforce via `panic_common.rbac.validate_list_item_scopes` that every member item has the exact same `ScopeType` as the list (`SCOPE_MISMATCH`).
  - Only users with `GLOBAL_ADMIN` permission may use the `"View As"` perspective switcher (`panic_common.rbac.can_use_view_as`) or mutate Pre-Defined Sites (`/api/v1/sites`), Teams (`/api/v1/teams`), Security Zones (`/api/v1/zones`), RBAC permissions (`/api/v1/rbac`), and App-Wide System Settings (`/api/v1/settings`).
- **AR-2.6** **Default Dashboard Governance:**
  - Each user may select a personal `default_dashboard_id` from dashboards visible in their scope, or leave it unset (`None`) to inherit `SystemSettings.default_global_dashboard_id`.
  - `SystemSettings.default_global_dashboard_id` must reference a `GLOBAL` scope dashboard, can only be modified by a `GLOBAL_ADMIN`, and protects that dashboard from deletion or scope demotion while active.

## 3. Observability & Configuration

- **AR-3.1** Every setting comes from environment variables (`PANIC_*` or `PANIC_*_FILE` for Docker secrets) via `panic_server.conf`. No real hostnames, IPs, or secrets are committed to the repository (RFC 5737 / `example.com` / `.example.net` only in fixtures and tests).
- **AR-3.2** Structured JSON logs to stdout (`ts, level, component, logger, msg, request_id`) with `X-Request-ID` propagation via `RequestIdMiddleware`.
- **AR-3.3** Health (`/api/v1/health`), version (`/api/v1/version`), and Prometheus metrics (`/metrics`) endpoints follow `reference-app` conventions.

# PANIC — Portal for Accessing Networks, Infrastructure, and Compute

**PANIC** is a self-hosted, multi-user operations portal and session launcher. It does not stream
terminals or desktops and never stores credentials: it hands launches to native tools on the operator's
workstation or jump host (`ssh`, PuTTY, `mstsc.exe`, browser tabs, local applications).

## Key capabilities

- **Dashboards:** full-width 12-column grids of HOST and LIST widgets; edit mode with drag-to-move,
  corner resize and conflict-safe saves; personal default dashboard over an app-wide default.
- **Launchers:** URL (open in a new tab), SSH and LOCAL_APP (copy an interpolated command, optional URI
  handler), RDP (`.rdp` download). Commands use each user's SSH template and remote user.
  An item may combine protocols (e.g. SSH and URL for a device with a web UI; never SSH with RDP).
- **Scopes:** GLOBAL, TEAM and PERSONAL catalog items, lists and dashboards; lists stay same-scope.
- **Security zones:** the client IP, resolved through trusted proxies, maps to a zone, and unreachable
  items are dimmed or hidden.
- **Access:** local bootstrap admin, LDAP and OIDC sign-in. Permissions (`GLOBAL_ADMIN`,
  `CAN_ADD_GLOBAL`, `CAN_ADD_TEAM`) and team membership are managed in the app. Admins can
  "View As" any user.
- **Command palette:** Ctrl+K or `/` to search and launch items, lists and dashboards.

## Architecture

```
browser ──► panic-web (Vue 3 + Quasar SPA, nginx allow-list proxy) ──► panic-server (Django REST API) ──► MongoDB
```

- `Application/Web`: the SPA (Vue 3, Quasar 2, TypeScript, Vite). `proxy-paths.json` is the single
  list of server paths the web tier forwards.
- `Application/Server/panic_server`: the API (`/api/v1/*`), `.rdp` launcher, client-IP and zone
  resolution, and Prometheus `/metrics` (server port only).
- `Application/Common/panic_common`: a pure domain library (models, normalisation, hygiene, zone
  resolver, RBAC), kept dependency-free by `import-linter`.
- `Build/Containers`: both images and the compose files. `Build/ci`: the CI scripts.
- `Documents/`: architecture rules, API contract, data model and ADRs (`Architecture/`),
  operations (`Operations/DEPLOYMENT.md`, `CONFIGURATION.md`, `PERFORMANCE.md`), UI design and
  the changelog. `SPEC.md`: the full specification.

## Quick start (development)

```bash
./panic setup     # Python venv, pinned Node, npm ci, .env
./panic start     # dev MongoDB, API on :8121, web UI on http://<this host>:8120
./panic test      # pytest, ruff, mypy, import-linter
(cd Application/Web && npm test && npm run lint && npm run typecheck)
```

To deploy, see [`Documents/Operations/DEPLOYMENT.md`](Documents/Operations/DEPLOYMENT.md).

## License

GPL-3.0-or-later.

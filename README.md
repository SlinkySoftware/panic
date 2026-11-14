# PANIC — Portal for Accessing Networks, Infrastructure, and Compute

**PANIC** is a lightweight, self-hosted, multi-user enterprise operations portal and jump-host session launcher. Unlike heavy HTML5 session proxies that stream terminal or desktop video over WebSockets and store credentials on the server, PANIC acts as a zero-install control plane that hands off execution directly to native workstation and jump-host tools (`ssh`, PuTTY, `mstsc.exe`, browser tabs, and local SOE binaries).

## Key Capabilities

- **Zabbix-Style Full-Width 12-Column Dashboards**:
  - Locked View Mode for one-click operations and Unlocked Edit Mode (`/dashboard/<dash-uuid>/edit`) with drag-and-drop widget reordering and bottom-right corner drag-resize handles.
  - Strictly two focused widget types: **Individual Host Card (`HOST`)** and **Endpoint List Table Card (`LIST`)** with drag-and-drop row ordering.
  - Explicit, bookmarkable browser URLs for every dashboard and portal screen (`pushState` / `replaceState` / `popstate`).
  - Two-tier Default Dashboard hierarchy: personal **User Default Dashboard** override inheriting from the **App-Wide Default Global Dashboard**.
- **Zero-Install Protocol Launchers (`WEB`, `SSH`, `RDP`, `LOCAL_APP`)**:
  - Protocol-aware target definitions, personalized SSH CLI template interpolation, and ephemeral in-memory `.rdp` file streaming (`Content-Type: application/x-rdp`) with strict control-character sanitization.
- **Unified Scope Model (`GLOBAL`, `TEAM`, `PERSONAL`) & Same-Scope Lists**:
  - Shared scoping across Catalog Items, Endpoint Lists, and Dashboards, enforcing same-scope membership on lists (`SCOPE_MISMATCH`) and pre-defined site codes (`/sites`).
- **Security Zones & Source IP Reachability (`/zones`)**:
  - Longest-prefix CIDR matching (IPv4 & IPv6) resolving the operator's connecting jump-host Zone and dimming or hiding unreachable targets.
- **In-App RBAC & Admin "View As" (`/rbac`)**:
  - Granular permissions (`GLOBAL_ADMIN`, `CAN_ADD_GLOBAL`, `CAN_ADD_TEAM`) plus an Admin **"View As"** perspective switcher to verify any user's dashboards, navigation rail, and scope visibility.

## Repository Layout

- `Application/Common/panic_common` — Pure Python domain library (Pydantic v2 schemas, normalization/deduplication, credential hygiene, IPv4/IPv6 CIDR zone resolver, RBAC & scope validation, `.rdp` & CLI template interpolators). Enforced dependency-free via `import-linter` (`AR-1.1`).
- `Application/Server/panic_server` — Django server rendering the reference-ui-aligned dark-first UI, REST API (`/api/v1/*`), ephemeral `.rdp` streamer, and Prometheus metrics (`/metrics`).
- `Build/Containers` — Containerfile and Docker Compose stack.
- `Documents/` — Architecture rules (`Documents/Architecture/ARCHITECTURE.md`), Data Model (`Documents/Architecture/DATA_MODEL.md`), UI Design (`Documents/UI_DESIGN.md`), Development Tasks (`Documents/TASKS.md`), and Session Status (`Documents/SESSION_STATUS.md`).
- `SPEC.md` — Full functional and architectural specification.

## Quick Start

```bash
# Initialize virtual environment, editable packages, and default .env
./panic setup

# Start the development server (default http://0.0.0.0:8120)
./panic start

# Run the full test and static analysis suite (pytest, ruff, mypy, import-linter)
./panic test
```

## License

GPL-3.0-or-later.

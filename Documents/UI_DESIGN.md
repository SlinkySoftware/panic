# PANIC — UI Design System

Aligned directly with **reference-ui** (`Documents/UI_DESIGN.md` & `src/css/app.css`) so PANIC feels like a sister application built by the same engineering team.

## 1. Visual Tokens (Adopted from reference-ui)
- **Brand Palette**: Deep Teal `--brand-500` (`#0f766e` light / `#2ebfae` dark), `--brand-400` (`#14958a` / `#3ccfbd`), `--brand-600` (`#0b5f58` / `#23a294`).
- **Dark-First Operations Theme (`body.body--dark` default)**:
  - `--page-bg: #1c1c1e`
  - `--surface: #242426`
  - `--surface-raised: #2c2c2e`
  - `--surface-sunken: #1a1a1c`
  - `--rail-bg: #212123`
  - `--header-bg: rgba(36, 36, 38, 0.86)` with `backdrop-filter: saturate(180%) blur(12px)`
  - Hairline borders (`--border: rgba(255, 255, 255, 0.09)`, `--border-strong: rgba(255, 255, 255, 0.16)`)
- **Semantic Status & Protocol Tones**:
  - `--status-ok` (`#30d158` dark / `#15803d` light): Verified / Reachable / Active
  - `--status-degraded` (`#ffb340` dark / `#a85a00` light): Zone Mismatch / View As Active / Edit Mode
  - `--status-blocked` (`#ff6961` dark / `#c62828` light): Blocked / Hygiene Violation / Delete Action
  - `--status-offline` (`#a1a1a6` dark / `#5b6472` light): Unclassified / Metadata Pill
  - Protocol pills using `--cache-hit` (WEB blue), `--brand-500` (SSH teal), `--cache-stale` (RDP violet), `--cache-miss` (LOCAL_APP amber).
- **Typography**: `Inter` for UI labels and hierarchy, `JetBrains Mono` (`.mono`) for hostnames, URLs, commands, CIDRs, site codes, and interpolated CLI commands; `font-variant-numeric: tabular-nums` on all ports, metrics, and counters.

## 2. Shell, Navigation Rail & Full-Width Zabbix Grid
- **Top Bar**:
  - Brand mark + `PANIC` wordmark with full definition (`Portal for Accessing Networks, Infrastructure, and Compute`) stacked directly underneath.
  - `STAGE 1 MOCK` status badge.
  - Command Palette trigger (`Ctrl+K` / `/`).
  - **Admin "View As" Perspective Switcher**: Visible to users with `GLOBAL_ADMIN` permission, allowing instant preview of dashboards, left-hand navigation, catalog items, and lists as any other user.
  - **Interactive Context Switcher**: Live popover for switching Active RBAC User, Source IP, and Security Zone override.
  - Comfort / Compact density toggle & Dark / Light theme toggle.
- **Collapsible Left Navigation Rail** (`232px` expanded, `64px` mini):
  - All navigation items are real `<a href="...">` links with visible browser URLs and HTML5 History (`pushState` / `replaceState` / `popstate`) synchronization.
  - **Dashboards** group: User's pinned, `always_display`, and Default Global dashboards (`<a href="/dashboard/<dash-uuid>">`) + `+` button opening the **"Add Existing (Global / Team)" / "+ Create New"** modal.
    - The user's effective **Default Dashboard** displays a `★` badge in the rail.
    - Dashboards with `always_display` enabled show a `📌` indicator and cannot be unpinned; the active **Default Global Dashboard** is also protected from unpinning and deletion.
  - **Resources & Lists** group: **Catalog Items** (`/catalog`) followed by **Endpoint Lists** (`/lists`).
  - **Scope, Zones & RBAC** group: **Pre-Defined Sites** (`/sites`), **Teams** (`/teams`), **Zones & IP CIDRs** (`/zones`), **RBAC Permissions** (`/rbac`).
  - **System** group: **System Settings** (`/settings`), **SSH & User Profile** (`/profile`), **Audit Log** (`/audit`).
- **Explicit Browser URL Routing (No Hidden URLs)**:
  - `<url>/` and `<url>/dashboard`: Resolve to the active user's effective Default Dashboard and canonicalize the browser address bar to `<url>/dashboard/<dash-uuid>`.
  - `<url>/dashboard/<dash-uuid>`: Opens the specific dashboard in Locked (View) Mode.
  - `<url>/dashboard/<dash-uuid>/edit`: Opens the specific dashboard directly in Unlocked (Edit) Mode (for users with write access to the dashboard's scope).
  - `<url>/catalog`, `<url>/lists`, `<url>/sites`, `<url>/teams`, `<url>/zones`, `<url>/rbac`, `<url>/settings`, `<url>/profile`, `<url>/audit`: Direct bookmarkable URLs for every portal screen, also displayed in the page header breadcrumbs.
- **Default Dashboard Hierarchy (User Default vs. App-Wide Default Global Dashboard)**:
  - **User Default Dashboard**: Users can set any dashboard available to them as their personal Default Dashboard via:
    1. The `☆ Set as My Default` / `★ My Default (Reset)` button on the dashboard header.
    2. The **My Default Dashboard** selector on **SSH & User Profile** (`/profile`) or **System Settings** (`/settings`).
    3. The `★ Set as My Default Dashboard` checkbox in **Dashboard Properties** or **+ Create New Dashboard**.
  - **App-Wide System Setting — Default Global Dashboard**: Global Admins can configure the system-wide **Default Global Dashboard** (`SystemSettings.default_global_dashboard_id`, restricted to `GLOBAL` scope dashboards) via **System Settings** (`/settings`) or **Dashboard Properties**. Users who have not set a personal override automatically inherit the Default Global Dashboard.
- **Main Content Area & Zabbix-Style 12-Column Grid**:
  - Uses 100% of available viewport width (`.ws-page { width: 100%; max-width: 100%; }`) so cards resize proportionally with the browser window.
  - **Locked View Mode vs. Unlocked Edit Mode**:
    - In Edit Mode (`/dashboard/<dash-uuid>/edit`), widgets feature a draggable header bar (`.widget-edit-bar`) for reordering and a bottom-right corner drag-resize handle (`.widget-resize-handle`) for interactive width (`3..12` columns) and height (`1..6` rows) resizing.
    - Dashboards include a `⚙ Dashboard Properties` button to edit Name, Description, Scope, Teams, `Always Display`, `Set as My Default Dashboard`, and (for Global Admins on Global dashboards) `Set as App-Wide Default Global Dashboard`.

## 3. Two-Card Resource Screens & Protocol-Aware Forms
- **Catalog Items (`/catalog`) & Endpoint Lists (`/lists`)**:
  - Both screens present **2 cards**: Card 1 for **Global & Team** items/lists and Card 2 for **Personal** items/lists.
  - Endpoint List tables and the Edit/Define List modal support drag-and-drop row ordering (`⠿`).
- **Protocol-Specific Catalog Item Modal**:
  - `WEB`: Target URL (`https://...`) + Pre-Defined Site dropdown.
  - `SSH`: Host / IP + SSH Port (default `22`) + Pre-Defined Site + SSH Command Line Options + Remote User Override.
  - `RDP`: Host / IP + RDP Port (default `3389`) + Pre-Defined Site + Domain\Username Override.
  - `LOCAL_APP`: Command / Executable Path + Pre-Defined Site + Command Line Options / Arguments (hiding Host and Port).

## 4. Quasar Implementation Mapping (Stage 6 panic-web)

The tokens above are CSS custom properties in `Application/Web/src/css/app.css` (dark set on
`body.body--dark`, light set otherwise). Quasar components map onto them as follows.

| Token / pattern | Quasar implementation |
|---|---|
| `--page-bg`, `--surface*`, `--rail-bg`, `--header-bg`, `--border*` | `q-layout` / `q-header` / `q-drawer` (`.panic-rail`) backgrounds and hairlines in `app.css`; cards are `q-card flat bordered`. |
| Brand teal `--brand-*` | Shell accents in `app.css`. Quasar's `primary` (buttons, toggles, active nav) is still Quasar's default blue: map `primary` to `--brand-500` (`setCssVar('primary', …)` in `boot/theme.ts`) if full brand alignment is wanted. |
| Status tones | `color="positive"` (ok / active), `warning` (edit mode, conflicts, View As), `negative` (delete, errors, hygiene failures), `grey-6` (disabled, unreachable). |
| Scope pills | `q-badge`: GLOBAL `primary`, TEAM `teal`, PERSONAL `grey-7`. |
| Protocol icons | Material icons: SSH `terminal`, RDP `desktop_windows`, WEB `language`, LOCAL_APP `apps`. |
| `.mono` | Hostnames, normalized targets, CIDRs, SSH templates and client-IP diagnostics (monospace inputs and cells). |
| Unreachable items | `opacity: 0.5` and the reason in a `q-tooltip` (DIM); omitted by the server under HIDE. |
| Two-card resource screens (§3) | Two server-paged `q-table` cards (`flat bordered`, `@request`), with search and filters in `#top-right`. |
| Forms | `q-dialog` + `q-form` on a single `row q-col-gutter-md` 12-column grid. Fields are `outlined dense hide-bottom-space`, so error text takes space only when shown. Server `fields` errors land on the matching input. |
| Dashboard grid (§2) | CSS grid, 12 columns, fixed row height. Edit mode: pointer-drag header to move, corner to resize, overlaps pushed down (`components/dashboard/grid.ts`, mirroring the server clamp). |
| Density / theme | Top-bar toggles (`stores/theme.ts`, per browser); Profile saves the same choices server-side. |

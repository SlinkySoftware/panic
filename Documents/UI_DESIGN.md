# PANIC — UI Design System

A dark-first operations look: neutral graphite surfaces, one teal brand colour, semantic status
tones and monospace for anything an operator might copy.

## 1. Visual Tokens
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
  - Protocol pills using `--cache-hit` (URL blue), `--brand-500` (SSH teal), `--cache-stale` (RDP violet), `--cache-miss` (LOCAL_APP amber).
- **Typography**: `Inter` for UI labels and hierarchy, `JetBrains Mono` (`.mono`) for hostnames, URLs, commands, CIDRs, site codes, and interpolated CLI commands; `font-variant-numeric: tabular-nums` on all ports, metrics, and counters.

## 2. Shell, Navigation Rail & Full-Width Grid
- **Top Bar**:
  - Brand mark + `PANIC` wordmark, with the full name (`Portal for Accessing Networks, Infrastructure, and Compute`) underneath on wider screens.
  - Command Palette trigger (`Ctrl+K` / `/`).
  - Zone badge: the caller's Security Zone, with a hint when it is the Default zone.
  - **View As** (Global Admins only): view the portal as another user, from another zone, or both. While it is active a banner shows the perspective with a **Stop View As** button; editing controls are disabled and the server refuses mutations.
  - Dark / Light theme toggle and the user menu (User Settings, Sign out). The layout is always compact (no density setting).
- **Collapsible Left Navigation Rail** (`232px` expanded, `64px` mini; expands on hover, "Keep menu open" pins it):
  - Every entry is a real link with a visible, bookmarkable URL (AR-1.4).
  - **Dashboards** group: the user's menu dashboards (pinned, `always_display`, the app-wide default and the user's default), then **Add dashboard** ("Add existing" / "Create new").
    - The user's effective default dashboard shows a star.
    - `always_display` dashboards and the app-wide default show a pin and cannot be removed from the menu.
  - **Resources** group: **Catalog** (`/catalog`), **Endpoint lists** (`/lists`).
  - **Scope** group: **Sites** (`/sites`), **Teams** (`/teams`), **Zones** (`/zones`), **Users** (`/settings/users`, admin only).
  - **System** group: **Application Settings** (`/settings`), **User Settings** (`/profile`), **Audit log** (`/audit`, admin only).
- **URLs**:
  - `/` and `/dashboard` resolve to the user's effective default dashboard and replace the address with `/dashboard/<uuid>`.
  - `/dashboard/<uuid>` opens a dashboard in view mode; `/dashboard/<uuid>/edit` opens it in edit mode (for users who may edit it).
  - `/rbac` redirects to `/settings/users`.
- **Default dashboards**:
  - **User default**: any dashboard visible to the user, set with the star on the dashboard header, the **My default dashboard** selector in User Settings, or "Make this my default dashboard" when creating one.
  - **App-wide default**: a `GLOBAL` dashboard chosen by a Global Admin in Application Settings. Users without their own default get it.
- **Dashboard grid** (12 columns, full viewport width, so cards resize with the window):
  - View mode: star (my default), pin (menu) and **Edit** in the dashboard header.
  - Edit mode: drag a widget's header to move it and its bottom-right corner to resize it (width `3..12` columns, height `1..6` rows). **Dashboard details** edits title, icon, description, `always_display` and deletion. A version conflict on save offers "Discard mine and reload" or "Overwrite theirs".

## 3. Two-Card Resource Screens & Protocol-Aware Forms
- **Catalog (`/catalog`) & Endpoint lists (`/lists`)**:
  - Both screens show **2 cards**: Card 1 for **Global & Team** items/lists and Card 2 for **Personal** items/lists.
  - List items are reordered only in the Edit List dialog, by dragging rows.
- **Application Settings (`/settings`)**: app-wide settings are greyed out with "Only super admins can change
  these settings." for other admins. Super admins also get a **Configuration** card: *Export config* (download)
  and *Import config* (file picker → preview dialog with per-section added / changed / unchanged / conflicts and
  the change list, ADD green, UPDATE blue, CONFLICT orange → "Import N changes" → confirmation).
- **Users**: the Super admin permission, its deep-purple badge and its filter option exist only for super admins;
  the bootstrap admin carries a "Bootstrap admin" badge and opens read-only for other admins.
- **Row actions**: Edit, **Copy**, Delete, in that order, on catalog items, sites, teams and zones. Copy opens the
  edit dialog prefilled from the row as a new record (title "Copy …"); Save stays disabled until a field changes.
- **Edit dialogs** (catalog item, site, team, zone): Save and Cancel sit in a column to the right of the fields
  (below them on phones), not in a bottom action bar.
- **Protocol-aware catalog item dialog**:
  - One Host field ("Host or URL" while URL is checked), then a **Protocols** checkbox list: SSH, RDP, URL,
    Local app. SSH and RDP are mutually exclusive: checking one disables the other.
  - Each checked protocol opens its row: Port (placeholder = default port) and `SSH` Arguments, `URL` Path and
    Full URL override, `LOCAL_APP` Command and Custom URI. `RDP` has Port only.
  - Account override shows when SSH, RDP or Local app is checked.
  - Every item: Title, Site, Scope, Teams, Zones (where the item is reachable), Tags, Description.
- **Multi-protocol items on dashboards and lists**: the row icon and click are the primary protocol (SSH or RDP,
  else URL, else Local app); each other protocol is an icon button on the right of the row.

## 4. Quasar Implementation Mapping

The tokens above are CSS custom properties in `Application/Web/src/css/app.css` (dark set on
`body.body--dark`, light set otherwise). Quasar components map onto them as follows.

| Token / pattern | Quasar implementation |
|---|---|
| `--page-bg`, `--surface*`, `--rail-bg`, `--header-bg`, `--border*` | `q-layout` / `q-header` / `q-drawer` (`.panic-rail`) backgrounds and hairlines in `app.css`; cards are `q-card flat bordered`. |
| Brand teal `--brand-*` | Shell accents in `app.css`. Quasar's `primary` (buttons, toggles, active nav) is still Quasar's default blue: map `primary` to `--brand-500` (`setCssVar('primary', …)` in `boot/theme.ts`) if full brand alignment is wanted. |
| Status tones | `color="positive"` (ok / active), `warning` (edit mode, conflicts, View As), `negative` (delete, errors, hygiene failures), `grey-6` (disabled, unreachable). |
| Scope pills | `q-badge`: GLOBAL `primary`, TEAM `teal`, PERSONAL `grey-7`. |
| Protocol icons | Material icons: SSH `terminal`, RDP `desktop_windows`, URL `language`, LOCAL_APP `apps`. |
| `.mono` | Hostnames, normalized targets, CIDRs, SSH templates and client-IP diagnostics (monospace inputs and cells). |
| Unreachable items | `opacity: 0.5` and the reason in a `q-tooltip` (DIM); omitted by the server under HIDE. |
| Two-card resource screens (§3) | Two server-paged `q-table` cards (`flat bordered`, `@request`), with search and filters in `#top-right`. |
| Forms | `q-dialog` + `q-form` on a single `row q-col-gutter-md` 12-column grid. Fields are `outlined dense hide-bottom-space`, so error text takes space only when shown. Server `fields` errors land on the matching input. |
| Dashboard grid (§2) | CSS grid, 12 columns, fixed row height. Edit mode: pointer-drag header to move, corner to resize, overlaps pushed down (`components/dashboard/grid.ts`, mirroring the server clamp). |
| Theme | Top-bar toggle (`stores/theme.ts`, per browser); User Settings saves it server-side. Always compact: no density setting. |

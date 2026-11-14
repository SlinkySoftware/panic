/**
 * PANIC Stage 1 Interactive UI Controller.
 * Implements:
 * - Zabbix-style Locked/Editable 12-column dashboard grid with 2 widget types:
 *   1. Individual Host Card (HOST)
 *   2. List Card (LIST)
 * - Scope model [Global, Team(s), Personal/Individual(s)] across Catalog Items,
 *   Endpoint Lists (strict same-scope item rule), and Dashboards.
 * - In-app RBAC (Global Admin, Can Add to Global Scope Items, Can Add Team Scope Items).
 * - Screens for Dashboards, Lists, Catalog, Teams, Zones & IP CIDRs, RBAC, Audit, and Profile.
 * - Zero-install launchers (WEB, SSH command copy, dynamic .rdp download, LOCAL_APP copy)
 *   and Ctrl+K / '/' Command Palette.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

(function () {
  "use strict";

  const stateEl = document.getElementById("panic-initial-state");
  const initialPayload = stateEl ? JSON.parse(stateEl.textContent || "{}") : {};
  const initialDashAttr = document.body.dataset.initialDashboardId || "";
  const initialEditAttr = document.body.dataset.initialEdit === "true";

  const appState = {
    snapshot: initialPayload,
    currentView: document.body.dataset.initialView || "dashboard",
    activeDashboardId:
      initialDashAttr ||
      (initialPayload.user && initialPayload.user.effective_default_dashboard_id) ||
      (initialPayload.dashboards && initialPayload.dashboards.length > 0
        ? initialPayload.dashboards[0].id
        : "d4f1a001-58cc-4372-a567-0e02b2c3d401"),
    editMode: initialEditAttr,
    workingDashboard: null,
    railCollapsed: false,
    simOpen: false,
    paletteOpen: false,
    paletteQuery: "",
    paletteIndex: 0,
    paletteItems: [],
    catalogFilterProtocol: "ALL",
    catalogFilterScope: "ALL",
    catalogSearch: "",
    listFilterScope: "ALL",
  };

  /* ------------------------------------------------------------------ Helpers */

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function csrfToken() {
    const cookie = document.cookie.split("; ").find((c) => c.startsWith("panic_csrftoken="));
    if (cookie) return decodeURIComponent(cookie.split("=")[1]);
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  async function apiRequest(path, method = "GET", body = null) {
    const opts = {
      method,
      headers: {
        Accept: "application/json",
      },
    };
    if (body !== null) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) {
      opts.headers["X-CSRFToken"] = csrfToken();
    }
    opts.credentials = "same-origin";
    const resp = await fetch(path, opts);
    if (resp.status === 401) {
      window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const msg =
        (data && data.detail) ||
        (data && data.error && data.error.message) ||
        `Request failed with status ${resp.status}`;
      throw new Error(msg);
    }
    return data;
  }

  function showToast(title, detail = "", tone = "ok") {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    const badgeClass =
      tone === "ok"
        ? "tone-ok"
        : tone === "warn"
        ? "tone-degraded"
        : tone === "error"
        ? "tone-blocked"
        : "tone-brand";
    const icon =
      tone === "ok" ? "✓" : tone === "warn" ? "⚠" : tone === "error" ? "✕" : "ℹ";
    toast.innerHTML = `
      <span class="ws-badge ${badgeClass}">${icon}</span>
      <div style="flex:1; min-width:0;">
        <div style="font-weight:600;">${esc(title)}</div>
        ${
          detail
            ? `<div class="mono text-muted" style="margin-top:3px; font-size:12px; word-break:break-all;">${esc(detail)}</div>`
            : ""
        }
      </div>
    `;
    stack.appendChild(toast);
    setTimeout(() => {
      toast.remove();
    }, 4200);
  }

  async function copyToClipboard(text, label) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      showToast(`Copied ${label} to clipboard`, text, "ok");
    } catch (_err) {
      showToast(`Command ready (${label})`, text, "info");
    }
  }

  /* ------------------------------------------------------------------ RBAC & Scope Helpers */

  function getCurrentUser() {
    return (
      (appState.snapshot && appState.snapshot.user) || {
        id: "usr-admin",
        username: "joperator",
        display_name: "Jordan Operator (Global Admin)",
        team_ids: [],
        permissions: ["GLOBAL_ADMIN", "CAN_ADD_GLOBAL", "CAN_ADD_TEAM"],
      }
    );
  }

  function getAuthUser() {
    return (appState.snapshot && appState.snapshot.auth_user) || getCurrentUser();
  }

  function getAccessibleDashboards() {
    return (
      (appState.snapshot &&
        (appState.snapshot.accessible_dashboards || appState.snapshot.dashboards)) ||
      []
    );
  }

  function getSystemSettings() {
    return (
      (appState.snapshot && appState.snapshot.system_settings) || {
        default_global_dashboard_id: "d4f1a001-58cc-4372-a567-0e02b2c3d401",
        updated_by: "joperator",
        updated_at: "2026-06-28T00:00:00Z",
      }
    );
  }

  function getEffectiveDefaultDashboardId() {
    const u = getCurrentUser();
    if (u && u.effective_default_dashboard_id) {
      return u.effective_default_dashboard_id;
    }
    const sys = (appState.snapshot && appState.snapshot.system_settings) || {};
    if (sys.default_global_dashboard_id) {
      return sys.default_global_dashboard_id;
    }
    const list = appState.snapshot.dashboards || [];
    return list.length > 0 ? list[0].id : "";
  }

  function getCanonicalUrl() {
    if (appState.currentView === "dashboard") {
      const dash = getActiveDashboard();
      const dashId = (dash && dash.id) || appState.activeDashboardId || getEffectiveDefaultDashboardId();
      if (!dashId) return "/dashboard";
      return appState.editMode
        ? `/dashboard/${encodeURIComponent(dashId)}/edit`
        : `/dashboard/${encodeURIComponent(dashId)}`;
    }
    const validViews = new Set([
      "catalog",
      "lists",
      "sites",
      "teams",
      "zones",
      "rbac",
      "settings",
      "profile",
      "audit",
    ]);
    if (validViews.has(appState.currentView)) {
      return `/${appState.currentView}`;
    }
    return "/dashboard";
  }

  function syncBrowserUrl(replace = false) {
    if (typeof window === "undefined" || !window.history) return;
    const targetPath = getCanonicalUrl();
    const currentPath = window.location.pathname;
    if (currentPath !== targetPath) {
      if (replace) {
        window.history.replaceState({}, "", targetPath);
      } else {
        window.history.pushState({}, "", targetPath);
      }
    }
  }

  function applyPathFromBrowserLocation() {
    if (typeof window === "undefined" || !window.location) return;
    const rawPath = window.location.pathname || "/";
    const cleanPath = rawPath.length > 1 ? rawPath.replace(/\/+$/, "") : "/";

    const editMatch = cleanPath.match(/^\/dashboard\/([^/]+)\/edit$/);
    if (editMatch) {
      const requestedId = decodeURIComponent(editMatch[1]);
      appState.currentView = "dashboard";
      appState.activeDashboardId = requestedId;
      const dash = getActiveDashboard();
      if (dash && canWriteScope(dash.scope)) {
        appState.editMode = true;
        appState.workingDashboard = JSON.parse(JSON.stringify(dash));
      } else {
        appState.editMode = false;
        appState.workingDashboard = null;
      }
      return;
    }

    const dashMatch = cleanPath.match(/^\/dashboard\/([^/]+)$/);
    if (dashMatch) {
      appState.currentView = "dashboard";
      appState.activeDashboardId = decodeURIComponent(dashMatch[1]);
      appState.editMode = false;
      appState.workingDashboard = null;
      return;
    }

    if (cleanPath === "/" || cleanPath === "/dashboard") {
      appState.currentView = "dashboard";
      if (!initialDashAttr) {
        appState.activeDashboardId = getEffectiveDefaultDashboardId();
      }
      appState.editMode = false;
      appState.workingDashboard = null;
      return;
    }

    const viewMatch = cleanPath.match(
      /^\/(catalog|lists|sites|teams|zones|rbac|settings|profile|audit)$/
    );
    if (viewMatch) {
      appState.currentView = viewMatch[1];
      appState.editMode = false;
      appState.workingDashboard = null;
    }
  }

  function canUseViewAs() {
    const viewAs = (appState.snapshot && appState.snapshot.view_as) || {};
    if (typeof viewAs.can_view_as === "boolean") return viewAs.can_view_as;
    const auth = getAuthUser();
    return (auth.permissions || []).includes("GLOBAL_ADMIN");
  }

  function hasPermission(perm) {
    const u = getCurrentUser();
    const perms = u.permissions || [];
    if (perms.includes("GLOBAL_ADMIN")) return true;
    return perms.includes(perm);
  }

  function canWriteScope(scope) {
    const u = getCurrentUser();
    const perms = u.permissions || [];
    if (perms.includes("GLOBAL_ADMIN")) return true;
    if (scope === "GLOBAL") {
      return perms.includes("CAN_ADD_GLOBAL");
    }
    if (scope === "TEAM") {
      return perms.includes("CAN_ADD_TEAM");
    }
    if (scope === "PERSONAL") {
      return true;
    }
    return false;
  }

  function getTeamMap() {
    const map = {};
    for (const t of appState.snapshot.teams || []) {
      map[t.id] = t;
    }
    return map;
  }

  function getZoneMap() {
    const map = {};
    for (const z of appState.snapshot.zones || []) {
      map[z.id] = z;
    }
    return map;
  }

  function formatScopeLabel(scope) {
    if (scope === "GLOBAL") return "Global";
    if (scope === "TEAM") return "Team";
    if (scope === "PERSONAL") return "Personal";
    return scope || "Global";
  }

  function renderScopeBadge(scope, teamIds = [], ownerUsernames = []) {
    const teamMap = getTeamMap();
    if (scope === "GLOBAL") {
      return `<span class="ws-badge tone-brand" title="Global scope — no team restrictions">Global</span>`;
    }
    if (scope === "TEAM") {
      const codes = (teamIds || [])
        .map((id) => (teamMap[id] ? teamMap[id].code : id))
        .join(", ");
      const suffix = codes ? ` (${esc(codes)})` : "";
      return `<span class="ws-badge tone-hit" title="Team scope">Team${suffix}</span>`;
    }
    const owners = (ownerUsernames || []).join(", ");
    const title = owners ? `Personal scope (${owners})` : "Personal scope";
    return `<span class="ws-badge tone-stale" title="${esc(title)}">Personal</span>`;
  }

  function renderProtocolBadge(protocol) {
    switch (protocol) {
      case "WEB":
        return `<span class="ws-badge tone-hit" title="Web HTTPS/HTTP Endpoint">&#127760; WEB</span>`;
      case "SSH":
        return `<span class="ws-badge tone-brand" title="SSH CLI Session">&gt;_ SSH</span>`;
      case "RDP":
        return `<span class="ws-badge tone-stale" title="Remote Desktop (.rdp)">&#128421; RDP</span>`;
      case "LOCAL_APP":
        return `<span class="ws-badge tone-miss" title="Local Application">&gt;_ LOCAL_APP</span>`;
      default:
        return `<span class="ws-badge tone-offline">${esc(protocol)}</span>`;
    }
  }

  function formatHostDisplay(item) {
    if (!item) return "";
    if (item.host_port_display) return item.host_port_display;
    if (item.port) return `${item.host}:${item.port}`;
    return item.host;
  }

  function renderZoneBadges(zoneIds) {
    const zoneMap = getZoneMap();
    const sim = appState.snapshot.simulation || {};
    const activeZoneId = sim.resolved_zone ? sim.resolved_zone.id : null;

    if (!zoneIds || zoneIds.length === 0) {
      return `<span class="ws-badge tone-ok" title="Accessible from all Security Zones">All Zones</span>`;
    }
    return zoneIds
      .map((zid) => {
        const z = zoneMap[zid];
        const name = z ? z.name : zid;
        const isCurrent = activeZoneId && activeZoneId === zid;
        const tone = isCurrent ? "tone-ok" : "tone-offline";
        return `<span class="ws-badge ${tone}" title="Zone: ${esc(name)}">${esc(name)}</span>`;
      })
      .join(" ");
  }

  function renderLaunchButton(item, extraClass = "btn--sm") {
    const reach = item.reachability || { reachable: true, reason: "Reachable" };
    const labelMap = {
      WEB: "&#8599; Launch",
      SSH: "&gt;_ Launch",
      RDP: "&#11015; Launch",
      LOCAL_APP: "&#9889; Launch",
    };
    const label = labelMap[item.protocol] || "Launch";
    const btnTone = reach.reachable ? "btn--primary" : "btn--warn";
    const title = reach.reachable
      ? `Launch ${item.title} (${formatHostDisplay(item)})`
      : `${reach.reason} — Click to launch anyway`;

    return `<button type="button" class="btn ${btnTone} ${extraClass}" data-launch-item="${esc(
      item.id
    )}" title="${esc(title)}">${label}</button>`;
  }

  /* ------------------------------------------------------------------ Widget Renderers (HOST and LIST) */

  /**
   * Renders an Individual Host Card matching the exact user specification:
   * ------------------------------------
   * | Type + Icon
   * |
   * | Host    : xxxx.xxxx.xxxx.xxxx
   * | Site    : <Site Code>
   * | Zone(s) : DMZ
   * |
   * | Type    : <Global / Team / Personal>
   * |
   * |                         LAUNCH BUTTON
   * ------------------------------------
   */
  function renderHostCardInner(item) {
    if (!item) {
      return `
        <div class="page-card__body">
          <div class="text-muted">Host item not found or not visible in current scope.</div>
        </div>
      `;
    }
    const hostDisplay = formatHostDisplay(item);
    const siteDisplay = item.site || "2SYA";
    const reach = item.reachability || { reachable: true };
    const primaryTargetLabel =
      item.protocol === "WEB"
        ? "URL"
        : item.protocol === "LOCAL_APP"
        ? "Command"
        : "Host";

    return `
      <header class="page-card__head">
        <div class="page-card__titles" style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
          <div style="display:flex; align-items:center; gap:8px; min-width:0;">
            ${renderProtocolBadge(item.protocol)}
            <span class="page-card__title" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${esc(
              item.title
            )}">${esc(item.title)}</span>
          </div>
          ${
            !reach.reachable
              ? `<span class="ws-badge tone-degraded" title="${esc(reach.reason)}">Zone Mismatch</span>`
              : ""
          }
        </div>
      </header>
      <div class="host-card-body">
        <div class="host-kv-table">
          <div class="host-kv-key">${esc(primaryTargetLabel)}</div>
          <div class="host-kv-sep">:</div>
          <div class="host-kv-val mono" title="${esc(hostDisplay)}">${esc(hostDisplay)}</div>

          <div class="host-kv-key">Site</div>
          <div class="host-kv-sep">:</div>
          <div class="host-kv-val"><span class="ws-badge tone-offline mono">${esc(
            siteDisplay
          )}</span></div>

          <div class="host-kv-key">Zone(s)</div>
          <div class="host-kv-sep">:</div>
          <div class="host-kv-val">${renderZoneBadges(item.zone_ids)}</div>

          <div class="host-kv-key" style="margin-top:4px;">Type</div>
          <div class="host-kv-sep" style="margin-top:4px;">:</div>
          <div class="host-kv-val" style="margin-top:4px;">${renderScopeBadge(
            item.scope,
            item.team_ids,
            item.owner_usernames
          )}</div>
        </div>

        <div class="host-launch-row">
          ${renderLaunchButton(item)}
        </div>
      </div>
    `;
  }

  /**
   * Renders a List Card matching the exact user specification:
   * ----------------------------------------------------------------------------------------------
   * | List Title  (e.g. Routers)
   * ----------------------------------------------------------------------------------------------
   * | Type+icon | Host / Port                    | Site        | Zone(s)       | Type     | Launch
   * ----------------------------------------------------------------------------------------------
   * | >_SSH     | router1.network.example.com    | 2SYA        | DMZ           | Personal | <Launch Button>
   */
  function renderListCardInner(endpointList, customTitle = null, showManageActions = false) {
    if (!endpointList) {
      return `
        <div class="page-card__body">
          <div class="text-muted">List not found or not visible in current scope.</div>
        </div>
      `;
    }

    const catalogById = {};
    for (const item of appState.snapshot.catalog || []) {
      catalogById[item.id] = item;
    }

    const items =
      endpointList.items ||
      (endpointList.item_ids || []).map((id) => catalogById[id]).filter(Boolean);

    const displayTitle = customTitle || endpointList.title;
    const canEditList = canWriteScope(endpointList.scope);

    const rowsHtml =
      items.length === 0
        ? `<tr><td colspan="6" class="text-muted" style="text-align:center; padding:18px;">No hosts in this list yet.</td></tr>`
        : items
            .map(
              (item, idx) => `
          <tr>
            <td style="white-space:nowrap;">
              <div style="display:inline-flex; align-items:center; gap:6px;">
                ${renderProtocolBadge(item.protocol)}
              </div>
            </td>
            <td>
              <div class="mono" style="font-weight:600;">${esc(formatHostDisplay(item))}</div>
              <div class="text-muted" style="font-size:11px;">${esc(item.title)}</div>
            </td>
            <td><span class="ws-badge tone-offline mono">${esc(item.site || "2SYA")}</span></td>
            <td>${renderZoneBadges(item.zone_ids)}</td>
            <td>${renderScopeBadge(item.scope, item.team_ids, item.owner_usernames)}</td>
            <td style="text-align:right;">${renderLaunchButton(item, "btn--sm")}</td>
          </tr>
        `
            )
            .join("");

    return `
      <header class="page-card__head">
        <div class="page-card__titles">
          <h3 class="page-card__title">
            <span>&#9776; ${esc(displayTitle)}</span>
            ${renderScopeBadge(
              endpointList.scope,
              endpointList.team_ids,
              endpointList.owner_usernames
            )}
            <span class="ws-badge tone-offline tabular">${items.length} ${
      items.length === 1 ? "item" : "items"
    }</span>
          </h3>
          ${
            endpointList.description
              ? `<div class="page-card__caption">${esc(endpointList.description)}</div>`
              : ""
          }
        </div>
        <div class="page-card__actions">
          ${
            canEditList
              ? `<button type="button" class="btn btn--sm btn--ghost" data-edit-list="${esc(
                  endpointList.id
                )}" title="Edit list items">&#9998; Edit List</button>`
              : ""
          }
          ${
            showManageActions && canEditList
              ? `<button type="button" class="btn btn--sm btn--danger" data-delete-list="${esc(
                  endpointList.id
                )}" title="Delete list">&#128465;</button>`
              : ""
          }
        </div>
      </header>
      <div class="page-card__body page-card__body--flush" style="overflow-x:auto;">
        <table class="ws-table" data-list-table="${esc(endpointList.id)}">
          <thead>
            <tr>
              <th>Type+Icon</th>
              <th>Target (Host / URL / Command)</th>
              <th>Site</th>
              <th>Zone(s)</th>
              <th>Type</th>
              <th style="text-align:right;">Launch</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      </div>
    `;
  }

  /* ------------------------------------------------------------------ Launch Handler */

  async function triggerLaunch(itemId) {
    const item = (appState.snapshot.catalog || []).find((c) => c.id === itemId);
    if (!item) return;

    const launch = item.launch || {};
    if (item.protocol === "RDP") {
      window.location.href =
        launch.rdp_download_url || `/api/v1/launch/rdp/${encodeURIComponent(item.id)}.rdp`;
      showToast("Downloaded .rdp launcher", `${item.title} (${formatHostDisplay(item)})`, "ok");
      return;
    }

    if (item.protocol === "WEB") {
      const targetUrl =
        launch.web_url ||
        (item.host.startsWith("http") ? item.host : `https://${item.host}`);
      window.open(targetUrl, "_blank", "noopener,noreferrer");
      showToast("Launched Web Endpoint", targetUrl, "ok");
      return;
    }

    if (item.protocol === "SSH") {
      const cmd = launch.ssh_command || `ssh ${item.host}`;
      await copyToClipboard(cmd, "SSH command");
      return;
    }

    if (item.protocol === "LOCAL_APP") {
      const cmd = launch.local_app_command || item.path_or_args || item.host;
      await copyToClipboard(cmd, "Local App command");
    }
  }

  /* ------------------------------------------------------------------ Topbar & Rail Rendering */

  function renderTopBarSummary() {
    const sim = appState.snapshot.simulation || {};
    const user = getCurrentUser();
    const authUser = getAuthUser();
    const viewAs = appState.snapshot.view_as || {};
    const zoneEl = document.getElementById("sim-summary-zone");
    const ipEl = document.getElementById("sim-summary-ip");
    const userEl = document.getElementById("sim-summary-user");
    const dotEl = document.getElementById("sim-indicator-dot");
    const densityEl = document.getElementById("label-density");
    const themeEl = document.getElementById("label-theme");
    const userTopEl = document.getElementById("topbar-username");
    const railZoneEl = document.getElementById("rail-zone-pill");
    const viewAsWrap = document.getElementById("topbar-view-as-wrap");
    const viewAsBanner = document.getElementById("view-as-banner");

    const zoneName = sim.resolved_zone ? sim.resolved_zone.name : "Unclassified Zone";
    if (zoneEl) zoneEl.textContent = zoneName;
    if (ipEl) ipEl.textContent = sim.simulated_ip || "";
    if (userEl) userEl.textContent = user.username;
    if (dotEl) {
      dotEl.className = sim.resolved_zone ? "sim-dot" : "sim-dot sim-dot--warn";
    }
    if (densityEl && user) densityEl.textContent = user.density;
    if (themeEl && user) themeEl.textContent = user.theme;
    if (userTopEl && user) userTopEl.textContent = user.username;
    if (railZoneEl) {
      railZoneEl.textContent = zoneName;
      railZoneEl.className = sim.resolved_zone ? "ws-badge tone-ok" : "ws-badge tone-degraded";
    }

    if (viewAsWrap) {
      if (canUseViewAs()) {
        const users = appState.snapshot.users || [];
        const activeViewAsId = viewAs.active && viewAs.target_user ? viewAs.target_user.id : "";
        viewAsWrap.hidden = false;
        viewAsWrap.className = `view-as-control ${
          viewAs.active ? "view-as-control--active" : ""
        }`;
        viewAsWrap.innerHTML = `
          <span class="text-muted" title="Admin 'View As' — preview dashboards, navigation, catalog, and lists as another user">&#128065; View As:</span>
          <select id="topbar-view-as-select" class="view-as-select" aria-label="View As User">
            <option value="" ${!activeViewAsId ? "selected" : ""}>${esc(
          authUser.username
        )} (Self / Admin)</option>
            ${users
              .filter((u) => u.id !== authUser.id)
              .map(
                (u) => `
              <option value="${esc(u.id)}" ${u.id === activeViewAsId ? "selected" : ""}>
                ${esc(u.display_name)} (${esc(u.username)})
              </option>
            `
              )
              .join("")}
          </select>
        `;
        const sel = document.getElementById("topbar-view-as-select");
        if (sel) {
          sel.addEventListener("change", async () => {
            await updateViewAs(sel.value);
          });
        }
      } else {
        viewAsWrap.hidden = true;
        viewAsWrap.innerHTML = "";
      }
    }

    if (viewAsBanner) {
      if (viewAs.active && viewAs.target_user) {
        viewAsBanner.hidden = false;
        viewAsBanner.innerHTML = `
          <div>
            <strong>&#128065; Viewing As: ${esc(viewAs.target_user.display_name)} (<span class="mono">${esc(
          viewAs.target_user.username
        )}</span>)</strong>
            <span class="text-muted" style="margin-left:8px;">
              Showing dashboards, left-hand navigation menu, catalog items, and endpoint lists from ${esc(
                viewAs.target_user.username
              )}'s perspective.
            </span>
          </div>
          <button type="button" class="btn btn--sm" id="btn-exit-view-as">Exit View As (${esc(
            authUser.username
          )})</button>
        `;
        const exitBtn = document.getElementById("btn-exit-view-as");
        if (exitBtn) {
          exitBtn.addEventListener("click", async () => {
            await updateViewAs("");
          });
        }
      } else {
        viewAsBanner.hidden = true;
        viewAsBanner.innerHTML = "";
      }
    }

    document.body.classList.toggle("body--dark", user.theme === "DARK");
    document.body.classList.toggle("density--compact", user.density === "COMPACT");
  }

  async function updateViewAs(targetUserId) {
    try {
      appState.snapshot = await apiRequest("/api/v1/simulator", "POST", {
        view_as_user_id: targetUserId || "",
      });
      appState.editMode = false;
      appState.workingDashboard = null;
      if (appState.currentView === "dashboard") {
        appState.activeDashboardId = getEffectiveDefaultDashboardId();
      }
      renderAll();
      if (targetUserId) {
        const u = getCurrentUser();
        showToast(
          `Viewing As ${u.username}`,
          `Showing dashboards, default dashboard, navigation, and scopes for ${u.display_name}`,
          "warn"
        );
      } else {
        showToast("Exited View As", "Restored your Admin perspective", "ok");
      }
    } catch (err) {
      showToast("View As Failed", err.message, "error");
    }
  }

  function renderSimulatorPopover() {
    const popover = document.getElementById("sim-popover");
    const body = document.getElementById("sim-popover-body");
    if (!popover || !body) return;
    popover.hidden = !appState.simOpen;
    if (!appState.simOpen) return;

    const sim = appState.snapshot.simulation || {};
    const zones = appState.snapshot.zones || [];
    const users = appState.snapshot.users || [];
    const currentUser = getCurrentUser();

    const presetButtons = [
      { label: "Core Network (10.10.50.14)", ip: "10.10.50.14" },
      { label: "DMZ (10.20.100.15)", ip: "10.20.100.15" },
      { label: "DC Mgmt (172.16.40.10)", ip: "172.16.40.10" },
      { label: "Corporate LAN (198.51.100.25)", ip: "198.51.100.25" },
    ];

    body.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:12px;">
        <div>
          <label class="field-label">Active RBAC User Account</label>
          <select id="sim-user-select" class="select">
            ${users
              .map(
                (u) => `
              <option value="${esc(u.id)}" ${u.id === currentUser.id ? "selected" : ""}>
                ${esc(u.display_name)} (${esc(u.username)}) — [${
                  (u.permissions || []).join(", ") || "Personal Scope Only"
                }]
              </option>
            `
              )
              .join("")}
          </select>
        </div>

        <div>
          <label class="field-label">Simulated Source IPv4 / IPv6 Address</label>
          <div style="display:flex; gap:6px;">
            <input type="text" id="sim-ip-input" class="input mono" value="${esc(
              sim.simulated_ip || ""
            )}" />
            <button type="button" class="btn btn--primary" id="btn-sim-apply-ip">Apply IP</button>
          </div>
          <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;">
            ${presetButtons
              .map(
                (p) =>
                  `<button type="button" class="btn btn--sm" data-sim-ip="${esc(p.ip)}">${esc(
                    p.label
                  )}</button>`
              )
              .join("")}
          </div>
        </div>

        <div>
          <label class="field-label">Quick-Switch Security Zone Override</label>
          <div style="display:flex; flex-wrap:wrap; gap:6px;">
            <button type="button" class="btn btn--sm ${
              !sim.override_zone_id ? "btn--primary" : ""
            }" data-sim-zone="">Auto (From IP CIDR)</button>
            ${zones
              .map((z) => {
                const active = sim.override_zone_id === z.id;
                return `<button type="button" class="btn btn--sm ${
                  active ? "btn--primary" : ""
                }" data-sim-zone="${esc(z.id)}">${esc(z.name)}</button>`;
              })
              .join("")}
          </div>
        </div>
      </div>
    `;

    const userSelect = document.getElementById("sim-user-select");
    if (userSelect) {
      userSelect.addEventListener("change", async () => {
        await updateSimulation({ active_user_id: userSelect.value });
      });
    }

    const applyIpBtn = document.getElementById("btn-sim-apply-ip");
    if (applyIpBtn) {
      applyIpBtn.addEventListener("click", async () => {
        const ipVal = document.getElementById("sim-ip-input").value.trim();
        if (ipVal) await updateSimulation({ simulated_ip: ipVal, override_zone_id: "" });
      });
    }

    body.querySelectorAll("[data-sim-ip]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await updateSimulation({
          simulated_ip: btn.getAttribute("data-sim-ip"),
          override_zone_id: "",
        });
      });
    });

    body.querySelectorAll("[data-sim-zone]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await updateSimulation({ override_zone_id: btn.getAttribute("data-sim-zone") });
      });
    });
  }

  async function updateSimulation(patch) {
    try {
      appState.snapshot = await apiRequest("/api/v1/simulator", "POST", patch);
      if (patch.active_user_id && appState.currentView === "dashboard") {
        appState.editMode = false;
        appState.workingDashboard = null;
        appState.activeDashboardId = getEffectiveDefaultDashboardId();
      }
      renderAll();
      showToast("Updated Active Context", "Recalculated Zone, IP & RBAC visibility", "ok");
    } catch (err) {
      showToast("Simulation Update Failed", err.message, "error");
    }
  }

  function renderRail() {
    const rail = document.getElementById("rail-nav");
    const aside = document.getElementById("app-rail");
    if (!rail || !aside) return;

    aside.classList.toggle("shell__rail--mini", appState.railCollapsed);
    const visibleDashboards = appState.snapshot.dashboards || [];

    const dashItems = visibleDashboards
      .map((d) => {
        const isActive =
          appState.currentView === "dashboard" && appState.activeDashboardId === d.id;
        const scopeTag = formatScopeLabel(d.scope)[0];
        const isAlwaysDisplay =
          Boolean(d.always_display) && (d.scope === "GLOBAL" || d.scope === "TEAM");
        const isGlobalDefault = Boolean(d.is_global_default);
        const isUserDefault = Boolean(d.is_user_default);
        const isEffectiveDefault = Boolean(d.is_effective_default);
        const canRemoveFromMenu =
          visibleDashboards.length > 1 && !isAlwaysDisplay && !isGlobalDefault;
        const dashUrl = `/dashboard/${encodeURIComponent(d.id)}`;

        let iconHtml = "&#9638;";
        if (isEffectiveDefault) {
          iconHtml = "&#9733;";
        } else if (isAlwaysDisplay) {
          iconHtml = "&#128204;";
        }

        const tooltipParts = [`${d.title} (${formatScopeLabel(d.scope)})`];
        if (isUserDefault) tooltipParts.push("My Default Dashboard");
        else if (isEffectiveDefault) tooltipParts.push("Default Dashboard (Global)");
        if (isGlobalDefault) tooltipParts.push("App Default Global Dashboard");
        if (isAlwaysDisplay) tooltipParts.push("Always Display");
        tooltipParts.push(`URL: ${dashUrl}`);

        return `
        <div style="display:flex; align-items:center; gap:2px;">
          <a href="${esc(dashUrl)}" class="rail__item ${
          isActive ? "rail__item--active" : ""
        }" data-nav-dashboard="${esc(d.id)}" title="${esc(
          tooltipParts.join(" — ")
        )}" style="flex:1; min-width:0;">
            <span>${iconHtml}</span>
            <span class="rail__label">${esc(d.title)}</span>
            ${
              isEffectiveDefault
                ? `<span class="ws-badge tone-ok" style="font-size:10px; height:18px; padding:0 5px;" title="${
                    isUserDefault
                      ? "Your personal Default Dashboard"
                      : "Default Global Dashboard"
                  }">&#9733;</span>`
                : ""
            }
            <span class="ws-badge ${
              isAlwaysDisplay || isGlobalDefault ? "tone-hit" : "tone-offline"
            }" style="font-size:10px; height:18px; padding:0 5px;" title="${
          isAlwaysDisplay ? "Always Display enabled" : formatScopeLabel(d.scope)
        }">${esc(scopeTag)}</span>
          </a>
          ${
            canRemoveFromMenu && !appState.railCollapsed
              ? `<button type="button" class="btn btn--ghost btn--sm" data-unpin-dashboard="${esc(
                  d.id
                )}" title="Remove from my Dashboards menu" style="height:24px; width:22px; padding:0; font-size:11px; color:var(--text-tertiary);">&times;</button>`
              : ""
          }
        </div>
      `;
      })
      .join("");

    const navBtn = (view, icon, label, badge = "") => {
      const active = appState.currentView === view;
      const href = `/${view}`;
      return `
        <a href="${esc(href)}" class="rail__item ${
        active ? "rail__item--active" : ""
      }" data-nav-view="${view}" title="${esc(label)} (${esc(href)})">
          <span>${icon}</span>
          <span class="rail__label">${esc(label)}</span>
          ${badge}
        </a>
      `;
    };

    const listsCount = (appState.snapshot.lists || []).length;
    const catalogCount = (appState.snapshot.catalog || []).length;
    const sitesCount = (appState.snapshot.sites || []).length;
    const teamsCount = (appState.snapshot.teams || []).length;
    const zonesCount = (appState.snapshot.zones || []).length;

    rail.innerHTML = `
      <div class="rail__group">
        <span>Dashboards</span>
        <button type="button" class="btn btn--ghost btn--sm" id="btn-rail-new-dash" title="Add Existing or Create New Dashboard" style="height:20px; padding:0 5px;">+</button>
      </div>
      ${dashItems}

      <div class="rail__group">Resources &amp; Lists</div>
      ${navBtn(
        "catalog",
        "&#128218;",
        "Catalog Items",
        `<span class="ws-badge tone-brand tabular">${catalogCount}</span>`
      )}
      ${navBtn(
        "lists",
        "&#9776;",
        "Endpoint Lists",
        `<span class="ws-badge tone-offline tabular">${listsCount}</span>`
      )}

      <div class="rail__group">Scope, Zones &amp; RBAC</div>
      ${navBtn(
        "sites",
        "&#127970;",
        "Pre-Defined Sites",
        `<span class="ws-badge tone-offline tabular">${sitesCount}</span>`
      )}
      ${navBtn(
        "teams",
        "&#128101;",
        "Teams",
        `<span class="ws-badge tone-offline tabular">${teamsCount}</span>`
      )}
      ${navBtn(
        "zones",
        "&#127760;",
        "Zones &amp; IP CIDRs",
        `<span class="ws-badge tone-offline tabular">${zonesCount}</span>`
      )}
      ${navBtn("rbac", "&#128272;", "RBAC Permissions")}

      <div class="rail__group">System</div>
      ${navBtn("settings", "&#128736;", "System Settings")}
      ${navBtn("profile", "&#9881;", "SSH &amp; User Profile")}
      ${navBtn("audit", "&#128220;", "Audit Log")}
    `;

    rail.querySelectorAll("[data-nav-dashboard]").forEach((link) => {
      link.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;
        ev.preventDefault();
        const dashId = link.getAttribute("data-nav-dashboard");
        appState.currentView = "dashboard";
        appState.activeDashboardId = dashId;
        appState.editMode = false;
        appState.workingDashboard = null;
        renderAll();
      });
    });

    rail.querySelectorAll("[data-unpin-dashboard]").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const dashId = btn.getAttribute("data-unpin-dashboard");
        try {
          const res = await apiRequest("/api/v1/dashboards", "POST", {
            action: "remove_from_menu",
            dashboard_id: dashId,
          });
          appState.snapshot = res.state;
          if (appState.activeDashboardId === dashId) {
            appState.activeDashboardId = getEffectiveDefaultDashboardId();
          }
          renderAll();
          showToast("Removed from Menu", "Use '+' -> Add Existing to add it back anytime", "ok");
        } catch (err) {
          showToast("Could Not Remove Dashboard", err.message, "error");
        }
      });
    });

    rail.querySelectorAll("[data-nav-view]").forEach((link) => {
      link.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;
        ev.preventDefault();
        const view = link.getAttribute("data-nav-view");
        appState.currentView = view;
        appState.editMode = false;
        appState.workingDashboard = null;
        renderAll();
      });
    });

    const newDashBtn = document.getElementById("btn-rail-new-dash");
    if (newDashBtn) {
      newDashBtn.addEventListener("click", () => openDashboardMenuPopup("add_existing"));
    }
  }

  /* ------------------------------------------------------------------ Dashboard View (Locked / Editable Grid with HOST & LIST widgets) */

  function getActiveDashboard() {
    const menuList = appState.snapshot.dashboards || [];
    const accessibleList = getAccessibleDashboards();
    let found =
      menuList.find((d) => d.id === appState.activeDashboardId) ||
      accessibleList.find((d) => d.id === appState.activeDashboardId);
    if (!found) {
      const defId = getEffectiveDefaultDashboardId();
      found =
        menuList.find((d) => d.id === defId) ||
        accessibleList.find((d) => d.id === defId) ||
        menuList[0] ||
        accessibleList[0];
      if (found) {
        appState.activeDashboardId = found.id;
      }
    }
    return found || null;
  }

  function renderDashboardView(container) {
    const dash = appState.editMode ? appState.workingDashboard : getActiveDashboard();
    if (!dash) {
      container.innerHTML = `<div class="page-card"><div class="page-card__body">No dashboards available in current scope.</div></div>`;
      return;
    }

    const canEditDash = canWriteScope(dash.scope);
    const catalogById = {};
    for (const item of appState.snapshot.catalog || []) {
      catalogById[item.id] = item;
    }
    const listById = {};
    for (const lst of appState.snapshot.lists || []) {
      listById[lst.id] = lst;
    }

    const widgetsHtml = (dash.widgets || [])
      .map((w, idx) => {
        const colSpan = Math.max(3, Math.min(12, Number(w.grid_w) || 4));
        const rowSpan = Math.max(1, Math.min(6, Number(w.grid_h) || 1));
        const gridStyle = `grid-column: span ${colSpan}; grid-row: span ${rowSpan};`;

        const editToolbar = appState.editMode
          ? `
          <div class="widget-edit-bar" data-w-drag-handle="${idx}" title="Drag bar to reorder widget, or drag bottom-right corner to resize">
            <span class="mono" style="font-weight:600; display:inline-flex; align-items:center; gap:6px;">
              <span class="drag-handle">&#10495;</span>
              <span>${w.widget_type === "HOST" ? "Host Card" : "List Card"}</span>
              <span class="ws-badge tone-brand mono" data-w-dim-label="${idx}">W:${colSpan} &times; H:${rowSpan}</span>
            </span>
            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
              <span class="text-muted" style="font-size:11px;">&#8600; Drag corner to resize</span>
              <button type="button" class="btn btn--sm" data-w-move="${idx}" data-dir="-1" title="Move Earlier in Grid">&larr;</button>
              <button type="button" class="btn btn--sm" data-w-move="${idx}" data-dir="1" title="Move Later in Grid">&rarr;</button>
              <button type="button" class="btn btn--sm btn--danger" data-w-remove="${idx}" title="Remove Widget">&#10005;</button>
            </div>
          </div>
        `
          : "";

        let innerHtml = "";
        if (w.widget_type === "HOST") {
          const item = w.host_item || catalogById[w.catalog_item_id];
          innerHtml = renderHostCardInner(item);
        } else if (w.widget_type === "LIST") {
          const endpointList = w.resolved_list || listById[w.list_id];
          innerHtml = renderListCardInner(endpointList, w.title || null, false);
        }

        const resizeGrip = appState.editMode
          ? `<div class="widget-resize-handle" data-w-resize-grip="${idx}" title="Drag to resize widget width (3-12 cols) and height (1-6 rows)"></div>`
          : "";

        return `
          <section class="page-card" style="${gridStyle}" data-widget-id="${esc(
          w.id
        )}" data-widget-idx="${idx}" ${appState.editMode ? 'draggable="true"' : ""}>
            ${editToolbar}
            ${innerHtml}
            ${resizeGrip}
          </section>
        `;
      })
      .join("");

    const isAlwaysDisplay =
      Boolean(dash.always_display) && (dash.scope === "GLOBAL" || dash.scope === "TEAM");
    const isUserDefault = Boolean(dash.is_user_default);
    const isGlobalDefault = Boolean(dash.is_global_default);
    const isEffectiveDefault = Boolean(dash.is_effective_default);
    const routePath = `/dashboard/${dash.id}${appState.editMode ? "/edit" : ""}`;

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <a href="/dashboard" id="crumb-default-dash" title="Go to Default Dashboard (/dashboard)">Dashboards</a>
          <span>/</span>
          <span>${esc(formatScopeLabel(dash.scope))}</span>
          <span>/</span>
          <a href="/dashboard/${esc(dash.id)}" class="mono" id="crumb-dash-uuid" title="Direct Dashboard URL">${esc(
      routePath
    )}</a>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#9638;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">
              ${esc(dash.title)}
              ${renderScopeBadge(dash.scope, dash.team_ids, dash.owner_usernames)}
              ${
                isUserDefault
                  ? `<span class="ws-badge tone-ok" title="Set as your personal Default Dashboard">&#9733; My Default Dashboard</span>`
                  : isEffectiveDefault
                  ? `<span class="ws-badge tone-brand" title="Your active Default Dashboard (inherited from App-wide Default Global Dashboard)">&#9733; Default Dashboard</span>`
                  : ""
              }
              ${
                isGlobalDefault
                  ? `<span class="ws-badge tone-hit" title="App-wide System Setting: Default Global Dashboard">&#127760; Default Global Dashboard</span>`
                  : ""
              }
              ${
                isAlwaysDisplay
                  ? `<span class="ws-badge tone-hit" title="Forced onto the navigation menu for all users in scope">&#128204; Always Display</span>`
                  : ""
              }
              ${
                appState.editMode
                  ? `<span class="ws-badge tone-degraded">&#9998; EDIT MODE (Unlocked — Drag to Resize/Reorder)</span>`
                  : `<span class="ws-badge tone-ok">&#128274; View Mode (Locked)</span>`
              }
            </h1>
            <div class="page-header__caption">${esc(dash.description)}</div>
          </div>
          <div class="page-header__actions">
            ${
              !appState.editMode
                ? `
                  ${
                    !isUserDefault
                      ? `<button type="button" class="btn" id="btn-set-user-default" title="Set this dashboard as your personal Default Dashboard">&#9734; Set as My Default</button>`
                      : `<button type="button" class="btn btn--ghost" id="btn-clear-user-default" title="Clear personal default override and use the App-wide Default Global Dashboard">&#9733; My Default (Reset)</button>`
                  }
                  <button type="button" class="btn" id="btn-new-dashboard">+ New Dashboard</button>
                  ${
                    canEditDash
                      ? `<button type="button" class="btn" id="btn-dash-properties" title="Edit Dashboard Name, Description, Scope, Default Settings, and Always Display">&#9881; Dashboard Properties</button>
                         <button type="button" class="btn btn--primary" id="btn-enter-edit">&#9998; Edit Dashboard</button>`
                      : `<button type="button" class="btn" disabled title="RBAC permission required to edit ${esc(
                          dash.scope
                        )} dashboard">&#128274; Locked (${esc(formatScopeLabel(dash.scope))})</button>`
                  }
                `
                : `
                  <button type="button" class="btn" id="btn-dash-properties" title="Edit Dashboard Name, Description, Scope, Default Settings, and Always Display">&#9881; Dashboard Properties</button>
                  <button type="button" class="btn" id="btn-add-widget">+ Add Widget (Host or List)</button>
                  <button type="button" class="btn btn--primary" id="btn-save-dash">&#10003; Save Dashboard</button>
                  <button type="button" class="btn btn--ghost" id="btn-cancel-edit">Cancel</button>
                `
            }
          </div>
        </div>
      </header>

      <div class="zabbix-grid ${appState.editMode ? "zabbix-grid--editing" : ""}" id="dashboard-zabbix-grid">
        ${
          widgetsHtml ||
          `<div class="page-card" style="grid-column: span 12;"><div class="page-card__body text-muted">This dashboard has no widgets yet. Click <strong>Edit Dashboard</strong> &rarr; <strong>+ Add Widget (Host or List)</strong> to add cards.</div></div>`
        }
      </div>
    `;

    const crumbDefault = document.getElementById("crumb-default-dash");
    if (crumbDefault) {
      crumbDefault.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;
        ev.preventDefault();
        appState.currentView = "dashboard";
        appState.activeDashboardId = getEffectiveDefaultDashboardId();
        appState.editMode = false;
        appState.workingDashboard = null;
        renderAll();
      });
    }

    const crumbUuid = document.getElementById("crumb-dash-uuid");
    if (crumbUuid) {
      crumbUuid.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;
        ev.preventDefault();
        copyToClipboard(window.location.origin + routePath, "Dashboard URL");
      });
    }

    const setDefBtn = document.getElementById("btn-set-user-default");
    if (setDefBtn) {
      setDefBtn.addEventListener("click", async () => {
        try {
          const res = await apiRequest("/api/v1/dashboards", "POST", {
            action: "set_user_default",
            dashboard_id: dash.id,
          });
          appState.snapshot = res.state;
          renderAll();
          showToast(
            "Default Dashboard Updated",
            `'${dash.title}' is now your personal Default Dashboard`,
            "ok"
          );
        } catch (err) {
          showToast("Could Not Set Default Dashboard", err.message, "error");
        }
      });
    }

    const clearDefBtn = document.getElementById("btn-clear-user-default");
    if (clearDefBtn) {
      clearDefBtn.addEventListener("click", async () => {
        try {
          const res = await apiRequest("/api/v1/dashboards", "POST", {
            action: "set_user_default",
            dashboard_id: "",
          });
          appState.snapshot = res.state;
          renderAll();
          showToast(
            "Reverted to Default Global Dashboard",
            "Cleared personal default override",
            "ok"
          );
        } catch (err) {
          showToast("Could Not Reset Default Dashboard", err.message, "error");
        }
      });
    }

    const propsBtn = document.getElementById("btn-dash-properties");
    if (propsBtn) {
      propsBtn.addEventListener("click", () => openDashboardPropertiesModal(dash));
    }

    const enterEditBtn = document.getElementById("btn-enter-edit");
    if (enterEditBtn) {
      enterEditBtn.addEventListener("click", () => {
        appState.workingDashboard = JSON.parse(JSON.stringify(getActiveDashboard()));
        appState.editMode = true;
        renderAll();
      });
    }

    const cancelEditBtn = document.getElementById("btn-cancel-edit");
    if (cancelEditBtn) {
      cancelEditBtn.addEventListener("click", () => {
        appState.editMode = false;
        appState.workingDashboard = null;
        renderAll();
      });
    }

    const saveDashBtn = document.getElementById("btn-save-dash");
    if (saveDashBtn) {
      saveDashBtn.addEventListener("click", async () => {
        try {
          appState.snapshot = await apiRequest(
            `/api/v1/dashboards/${encodeURIComponent(appState.workingDashboard.id)}/layout`,
            "PUT",
            appState.workingDashboard
          );
          appState.editMode = false;
          appState.workingDashboard = null;
          renderAll();
          showToast("Dashboard Saved", "Widget positions and sizes updated", "ok");
        } catch (err) {
          showToast("Save Failed", err.message, "error");
        }
      });
    }

    const addWidgetBtn = document.getElementById("btn-add-widget");
    if (addWidgetBtn) {
      addWidgetBtn.addEventListener("click", () => openAddWidgetModal());
    }

    const newDashBtn = document.getElementById("btn-new-dashboard");
    if (newDashBtn) {
      newDashBtn.addEventListener("click", () => openDashboardMenuPopup("add_existing"));
    }

    container.querySelectorAll("[data-w-move]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-w-move"));
        const dir = Number(btn.getAttribute("data-dir"));
        const arr = appState.workingDashboard.widgets;
        const target = idx + dir;
        if (target >= 0 && target < arr.length) {
          const tmp = arr[idx];
          arr[idx] = arr[target];
          arr[target] = tmp;
          renderAll();
        }
      });
    });

    container.querySelectorAll("[data-w-remove]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-w-remove"));
        appState.workingDashboard.widgets.splice(idx, 1);
        renderAll();
      });
    });

    // Interactive Drag-Resize for Dashboard Widgets (replaces W+/W-/H+/H- buttons)
    container.querySelectorAll("[data-w-resize-grip]").forEach((grip) => {
      grip.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const idx = Number(grip.getAttribute("data-w-resize-grip"));
        const w = appState.workingDashboard && appState.workingDashboard.widgets[idx];
        if (!w) return;

        const cardEl = grip.closest(".page-card");
        const gridEl = document.getElementById("dashboard-zabbix-grid");
        if (!cardEl || !gridEl) return;

        const gridRect = gridEl.getBoundingClientRect();
        const startRect = cardEl.getBoundingClientRect();
        const startX = ev.clientX;
        const startY = ev.clientY;
        const startW = Math.max(3, Math.min(12, Number(w.grid_w) || 4));
        const startH = Math.max(1, Math.min(6, Number(w.grid_h) || 1));
        const colWidth = Math.max(40, gridRect.width / 12);
        const rowUnit = Math.max(110, startRect.height / startH);
        const dimBadge = cardEl.querySelector(`[data-w-dim-label="${idx}"]`);

        cardEl.classList.add("page-card--resizing");
        if (grip.setPointerCapture) {
          try {
            grip.setPointerCapture(ev.pointerId);
          } catch (_e) {
            // ignore pointer capture unsupported in synthetic events
          }
        }

        function onPointerMove(moveEv) {
          const dx = moveEv.clientX - startX;
          const dy = moveEv.clientY - startY;
          const dCols = Math.round(dx / colWidth);
          const dRows = Math.round(dy / rowUnit);
          const nextW = Math.max(3, Math.min(12, startW + dCols));
          const nextH = Math.max(1, Math.min(6, startH + dRows));
          w.grid_w = nextW;
          w.grid_h = nextH;
          cardEl.style.gridColumn = `span ${nextW}`;
          cardEl.style.gridRow = `span ${nextH}`;
          if (dimBadge) {
            dimBadge.innerHTML = `W:${nextW} &times; H:${nextH}`;
          }
        }

        function onPointerUp() {
          window.removeEventListener("pointermove", onPointerMove);
          window.removeEventListener("pointerup", onPointerUp);
          window.removeEventListener("pointercancel", onPointerUp);
          cardEl.classList.remove("page-card--resizing");
          renderAll();
        }

        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerUp);
      });
    });

    // Drag-and-drop widget card reordering in Edit Mode
    if (appState.editMode) {
      let draggedWidgetIdx = null;
      container.querySelectorAll(".page-card[data-widget-idx]").forEach((cardEl) => {
        cardEl.addEventListener("dragstart", (ev) => {
          draggedWidgetIdx = Number(cardEl.getAttribute("data-widget-idx"));
          cardEl.classList.add("draggable-row--dragging");
          if (ev.dataTransfer) {
            ev.dataTransfer.effectAllowed = "move";
            ev.dataTransfer.setData("text/plain", String(draggedWidgetIdx));
          }
        });
        cardEl.addEventListener("dragend", () => {
          draggedWidgetIdx = null;
          cardEl.classList.remove("draggable-row--dragging");
          container.querySelectorAll(".page-card--drop-target").forEach((el) => {
            el.classList.remove("page-card--drop-target");
          });
        });
        cardEl.addEventListener("dragover", (ev) => {
          if (draggedWidgetIdx === null) return;
          const targetIdx = Number(cardEl.getAttribute("data-widget-idx"));
          if (targetIdx === draggedWidgetIdx) return;
          ev.preventDefault();
          cardEl.classList.add("page-card--drop-target");
        });
        cardEl.addEventListener("dragleave", () => {
          cardEl.classList.remove("page-card--drop-target");
        });
        cardEl.addEventListener("drop", (ev) => {
          if (draggedWidgetIdx === null) return;
          const targetIdx = Number(cardEl.getAttribute("data-widget-idx"));
          cardEl.classList.remove("page-card--drop-target");
          if (
            targetIdx !== draggedWidgetIdx &&
            appState.workingDashboard &&
            Array.isArray(appState.workingDashboard.widgets)
          ) {
            ev.preventDefault();
            const arr = appState.workingDashboard.widgets;
            const [moved] = arr.splice(draggedWidgetIdx, 1);
            arr.splice(targetIdx, 0, moved);
            draggedWidgetIdx = null;
            renderAll();
          }
        });
      });
    }

  }

  function openAddWidgetModal() {
    const catalog = appState.snapshot.catalog || [];
    const lists = appState.snapshot.lists || [];

    openModal(
      "Add Widget to Dashboard",
      `
      <div>
        <label class="field-label">Widget Type (Dashboards support Host or List cards only)</label>
        <select id="mw-type" class="select">
          <option value="HOST">Host — Individual Host Card</option>
          <option value="LIST">List — Endpoint List Table Card</option>
        </select>
      </div>

      <div id="mw-host-picker">
        <label class="field-label">Select Host from Catalog</label>
        <select id="mw-item-id" class="select">
          ${catalog
            .map(
              (c) =>
                `<option value="${esc(c.id)}">[${esc(c.protocol)}] ${esc(
                  c.title
                )} — ${esc(formatHostDisplay(c))} (${esc(c.site || "2SYA")} / ${esc(
                  formatScopeLabel(c.scope)
                )})</option>`
            )
            .join("")}
        </select>
      </div>

      <div id="mw-list-picker" hidden>
        <label class="field-label">Select Endpoint List</label>
        <select id="mw-list-id" class="select">
          ${lists
            .map(
              (l) =>
                `<option value="${esc(l.id)}">${esc(l.title)} (${esc(
                  formatScopeLabel(l.scope)
                )} — ${(l.item_ids || []).length} items)</option>`
            )
            .join("")}
        </select>
      </div>

      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
        <div>
          <label class="field-label">Grid Width (3 to 12 columns)</label>
          <input type="number" id="mw-width" class="input" min="3" max="12" value="4" />
        </div>
        <div>
          <label class="field-label">Grid Height (1 to 6 rows)</label>
          <input type="number" id="mw-height" class="input" min="1" max="6" value="1" />
        </div>
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: "Add Widget",
          className: "btn btn--primary",
          onClick: () => {
            const wtype = document.getElementById("mw-type").value;
            const gridW = Math.max(
              3,
              Math.min(12, Number(document.getElementById("mw-width").value) || 4)
            );
            const gridH = Math.max(
              1,
              Math.min(6, Number(document.getElementById("mw-height").value) || 1)
            );
            const newWidget = {
              id: `w-${Date.now()}`,
              dashboard_id: appState.workingDashboard.id,
              widget_type: wtype,
              title: "",
              grid_x: 1,
              grid_y: 1,
              grid_w: gridW,
              grid_h: gridH,
              catalog_item_id: null,
              list_id: null,
            };
            if (wtype === "HOST") {
              newWidget.catalog_item_id = document.getElementById("mw-item-id").value;
              const item = catalog.find((c) => c.id === newWidget.catalog_item_id);
              newWidget.title = item ? item.title : "Host";
              newWidget.host_item = item || null;
            } else {
              newWidget.list_id = document.getElementById("mw-list-id").value;
              const lst = lists.find((l) => l.id === newWidget.list_id);
              newWidget.title = lst ? lst.title : "List";
              newWidget.resolved_list = lst || null;
            }
            appState.workingDashboard.widgets.push(newWidget);
            closeModal();
            renderAll();
          },
        },
      ]
    );

    const typeSel = document.getElementById("mw-type");
    const hostPicker = document.getElementById("mw-host-picker");
    const listPicker = document.getElementById("mw-list-picker");
    const widthInput = document.getElementById("mw-width");
    if (typeSel) {
      typeSel.addEventListener("change", () => {
        const isHost = typeSel.value === "HOST";
        hostPicker.hidden = !isHost;
        listPicker.hidden = isHost;
        widthInput.value = isHost ? "4" : "12";
      });
    }
  }

  /**
   * Opens the Dashboards menu "+" popup allowing the user to choose between:
   * - "Add Existing" (adds an existing Global or Team dashboard to the user's left-hand menu)
   * - "Create New" (creates a new dashboard and adds it to the user's menu)
   */
  function openDashboardMenuPopup(initialMode = "add_existing") {
    const teams = appState.snapshot.teams || [];
    const currentUser = getCurrentUser();
    const canGlobal = canWriteScope("GLOBAL");
    const canTeam = canWriteScope("TEAM");
    const initialScope = canGlobal ? "GLOBAL" : canTeam ? "TEAM" : "PERSONAL";
    const selectedTeams = new Set(currentUser.team_ids || []);
    const sharedDashboards = appState.snapshot.available_dashboards || [];
    const unpinnedDashboards = sharedDashboards.filter((d) => !d.in_user_menu);
    let activeMode = initialMode === "create_new" ? "create_new" : "add_existing";

    const existingListHtml =
      sharedDashboards.length === 0
        ? `<div class="text-muted" style="padding:12px;">No Global or Team dashboards are visible in your scope yet. Switch to <strong>Create New</strong> to build one.</div>`
        : sharedDashboards
            .map((d, idx) => {
              const inMenu = Boolean(d.in_user_menu);
              const firstUnpinned = unpinnedDashboards[0] && unpinnedDashboards[0].id === d.id;
              return `
              <label class="chip-option" style="justify-content:space-between; width:100%; padding:10px 12px; ${
                inMenu ? "opacity:0.72;" : ""
              }">
                <span style="display:flex; align-items:flex-start; gap:10px; min-width:0;">
                  <input type="radio" name="md-existing-dash" value="${esc(d.id)}" ${
                firstUnpinned || (!unpinnedDashboards.length && idx === 0) ? "checked" : ""
              } ${inMenu ? "disabled" : ""} style="margin-top:3px;" />
                  <span>
                    <span style="font-weight:600; display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                      <span>${esc(d.title)}</span>
                      ${renderScopeBadge(d.scope, d.team_ids, d.owner_usernames)}
                      <span class="ws-badge tone-offline tabular">${(d.widgets || []).length} widgets</span>
                    </span>
                    <span class="text-muted" style="display:block; font-size:11px; margin-top:2px;">${esc(
                      d.description
                    )}</span>
                  </span>
                </span>
                <span>
                  ${
                    inMenu
                      ? `<span class="ws-badge tone-ok">&#10003; In Menu</span>`
                      : `<button type="button" class="btn btn--sm btn--primary" data-quick-add-dash="${esc(
                          d.id
                        )}">+ Add to Menu</button>`
                  }
                </span>
              </label>
            `;
            })
            .join("");

    openModal(
      "Dashboards Menu — Add Existing or Create New",
      `
      <div class="tab-switcher" role="tablist">
        <button type="button" class="tab-switcher__btn ${
          activeMode === "add_existing" ? "tab-switcher__btn--active" : ""
        }" id="tab-dash-add-existing">Add Existing (Global / Team)</button>
        <button type="button" class="tab-switcher__btn ${
          activeMode === "create_new" ? "tab-switcher__btn--active" : ""
        }" id="tab-dash-create-new">+ Create New</button>
      </div>

      <div id="panel-dash-add-existing" ${activeMode === "add_existing" ? "" : "hidden"}>
        <div class="text-muted" style="font-size:12px; margin-bottom:8px;">
          Select an existing <strong>Global</strong> or <strong>Team</strong> dashboard to add to your left-hand Dashboards menu (${esc(
            currentUser.username
          )}):
        </div>
        <div class="chip-select-grid" style="flex-direction:column; align-items:stretch; max-height:280px;">
          ${existingListHtml}
        </div>
      </div>

      <div id="panel-dash-create-new" ${
        activeMode === "create_new" ? "" : "hidden"
      } style="display:flex; flex-direction:column; gap:12px;">
        <div>
          <label class="field-label">Dashboard Name</label>
          <input type="text" id="md-title" class="input" placeholder="e.g., Core Routers &amp; Switching" />
        </div>
        <div>
          <label class="field-label">Description</label>
          <input type="text" id="md-desc" class="input" placeholder="Brief summary of this dashboard's operational purpose" />
        </div>
        <div>
          <label class="field-label">Scope [Global, Team(s), Individual(s)]</label>
          <select id="md-scope" class="select">
            <option value="GLOBAL" ${initialScope === "GLOBAL" ? "selected" : ""} ${
        !canGlobal ? "disabled" : ""
      }>Global (All Users) ${!canGlobal ? "— Requires Can Add Global permission" : ""}</option>
            <option value="TEAM" ${initialScope === "TEAM" ? "selected" : ""} ${
        !canTeam ? "disabled" : ""
      }>Team(s) (1 or more Teams) ${!canTeam ? "— Requires Can Add Team permission" : ""}</option>
            <option value="PERSONAL" ${
              initialScope === "PERSONAL" ? "selected" : ""
            }>Individual(s) / Personal (${esc(currentUser.username)})</option>
          </select>
        </div>
        <div id="md-teams-wrap" ${initialScope === "TEAM" ? "" : "hidden"}>
          <label class="field-label">Select Team(s)</label>
          <div class="chip-select-grid">
            ${teams
              .map(
                (t) => `
              <label class="chip-option">
                <input type="checkbox" name="md-team-cb" value="${esc(t.id)}" ${
                  selectedTeams.has(t.id) ? "checked" : ""
                } />
                <span class="mono" style="font-weight:600;">${esc(t.code)}</span>
                <span class="text-muted">${esc(t.name)}</span>
              </label>
            `
              )
              .join("")}
          </div>
        </div>
        <div id="md-always-display-wrap" ${
          initialScope === "GLOBAL" || initialScope === "TEAM" ? "" : "hidden"
        }>
          <label class="chip-option" style="width:100%;">
            <input type="checkbox" id="md-always-display" />
            <span>
              <strong>&#128204; Always Display on Menu</strong>
              <span class="text-muted" style="display:block; font-size:11px;">
                Forces this Global / Team dashboard onto the left-hand Dashboards menu for all users in scope.
              </span>
            </span>
          </label>
        </div>
        <div>
          <label class="chip-option" style="width:100%;">
            <input type="checkbox" id="md-user-default" />
            <span>
              <strong>&#9733; Set as My Default Dashboard</strong>
              <span class="text-muted" style="display:block; font-size:11px;">
                Opens this dashboard automatically when you visit <code>/dashboard</code>.
              </span>
            </span>
          </label>
        </div>
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: activeMode === "add_existing" ? "Add Existing to Menu" : "Create Dashboard",
          className: "btn btn--primary",
          onClick: async () => {
            if (activeMode === "add_existing") {
              const checked = document.querySelector(
                "input[name='md-existing-dash']:checked:not(:disabled)"
              );
              if (!checked) {
                showToast(
                  "All Visible Dashboards Added",
                  "Switch to '+ Create New' to create another dashboard",
                  "info"
                );
                return;
              }
              await addExistingDashboardToMenu(checked.value);
              return;
            }

            const title = document.getElementById("md-title").value.trim();
            const description = document.getElementById("md-desc").value.trim();
            const scope = document.getElementById("md-scope").value;
            const alwaysDisplayEl = document.getElementById("md-always-display");
            const userDefaultEl = document.getElementById("md-user-default");
            const alwaysDisplay =
              (scope === "GLOBAL" || scope === "TEAM") &&
              Boolean(alwaysDisplayEl && alwaysDisplayEl.checked);
            const setAsUserDefault = Boolean(userDefaultEl && userDefaultEl.checked);
            if (!title) {
              showToast("Validation Error", "Dashboard Name is required", "error");
              return;
            }
            const teamIds =
              scope === "TEAM"
                ? Array.from(document.querySelectorAll("input[name='md-team-cb']:checked")).map(
                    (el) => el.value
                  )
                : [];
            if (scope === "TEAM" && teamIds.length === 0) {
              showToast("Validation Error", "Select at least 1 team for Team scope", "error");
              return;
            }

            try {
              const res = await apiRequest("/api/v1/dashboards", "POST", {
                action: "create",
                title,
                description,
                scope,
                team_ids: teamIds,
                owner_usernames: scope === "PERSONAL" ? [currentUser.username] : [],
                always_display: alwaysDisplay,
                set_as_user_default: setAsUserDefault,
              });
              appState.snapshot = res.state;
              appState.activeDashboardId = res.created_dashboard_id;
              appState.currentView = "dashboard";
              closeModal();
              renderAll();
              showToast("Dashboard Created", `${title} (/dashboard/${res.created_dashboard_id})`, "ok");
            } catch (err) {
              showToast("Error Creating Dashboard", err.message, "error");
            }
          },
        },
      ]
    );

    const tabExisting = document.getElementById("tab-dash-add-existing");
    const tabCreate = document.getElementById("tab-dash-create-new");
    const panelExisting = document.getElementById("panel-dash-add-existing");
    const panelCreate = document.getElementById("panel-dash-create-new");
    const primaryFootBtn = document.querySelector("#modal-foot .btn--primary");

    function setTab(mode) {
      activeMode = mode;
      if (tabExisting) {
        tabExisting.classList.toggle("tab-switcher__btn--active", mode === "add_existing");
      }
      if (tabCreate) {
        tabCreate.classList.toggle("tab-switcher__btn--active", mode === "create_new");
      }
      if (panelExisting) panelExisting.hidden = mode !== "add_existing";
      if (panelCreate) panelCreate.hidden = mode !== "create_new";
      if (primaryFootBtn) {
        primaryFootBtn.textContent =
          mode === "add_existing" ? "Add Existing to Menu" : "Create Dashboard";
      }
    }

    if (tabExisting) tabExisting.addEventListener("click", () => setTab("add_existing"));
    if (tabCreate) tabCreate.addEventListener("click", () => setTab("create_new"));

    document.querySelectorAll("[data-quick-add-dash]").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        await addExistingDashboardToMenu(btn.getAttribute("data-quick-add-dash"));
      });
    });

    const scopeSel = document.getElementById("md-scope");
    const teamsWrap = document.getElementById("md-teams-wrap");
    const alwaysWrap = document.getElementById("md-always-display-wrap");
    if (scopeSel && teamsWrap) {
      scopeSel.addEventListener("change", () => {
        teamsWrap.hidden = scopeSel.value !== "TEAM";
        if (alwaysWrap) {
          alwaysWrap.hidden = scopeSel.value !== "GLOBAL" && scopeSel.value !== "TEAM";
        }
      });
    }
  }

  function openDashboardPropertiesModal(dash) {
    if (!dash) return;
    const teams = appState.snapshot.teams || [];
    const currentUser = getCurrentUser();
    const canGlobal = canWriteScope("GLOBAL");
    const canTeam = canWriteScope("TEAM");
    const selectedTeams = new Set(dash.team_ids || []);

    openModal(
      `Dashboard Properties — ${dash.title}`,
      `
      <div>
        <label class="field-label">Dashboard Name</label>
        <input type="text" id="mdp-title" class="input" value="${esc(dash.title)}" />
      </div>
      <div>
        <label class="field-label">Description</label>
        <input type="text" id="mdp-desc" class="input" value="${esc(dash.description || "")}" />
      </div>
      <div>
        <label class="field-label">Scope [Global, Team(s), Personal]</label>
        <select id="mdp-scope" class="select">
          <option value="GLOBAL" ${dash.scope === "GLOBAL" ? "selected" : ""} ${
        !canGlobal ? "disabled" : ""
      }>Global (All Users) ${!canGlobal ? "— Requires Can Add Global permission" : ""}</option>
          <option value="TEAM" ${dash.scope === "TEAM" ? "selected" : ""} ${
        !canTeam ? "disabled" : ""
      }>Team(s) (1 or more Teams) ${!canTeam ? "— Requires Can Add Team permission" : ""}</option>
          <option value="PERSONAL" ${
            dash.scope === "PERSONAL" ? "selected" : ""
          }>Personal (${esc(currentUser.username)})</option>
        </select>
      </div>
      <div id="mdp-teams-wrap" ${dash.scope === "TEAM" ? "" : "hidden"}>
        <label class="field-label">Assigned Team(s)</label>
        <div class="chip-select-grid">
          ${teams
            .map(
              (t) => `
            <label class="chip-option">
              <input type="checkbox" name="mdp-team-cb" value="${esc(t.id)}" ${
                selectedTeams.has(t.id) ? "checked" : ""
              } />
              <span class="mono" style="font-weight:600;">${esc(t.code)}</span>
              <span class="text-muted">${esc(t.name)}</span>
            </label>
          `
            )
            .join("")}
        </div>
      </div>
      <div id="mdp-always-display-wrap" ${
        dash.scope === "GLOBAL" || dash.scope === "TEAM" ? "" : "hidden"
      }>
        <label class="chip-option" style="width:100%;">
          <input type="checkbox" id="mdp-always-display" ${
            dash.always_display ? "checked" : ""
          } />
          <span>
            <strong>&#128204; Always Display on Menu</strong>
            <span class="text-muted" style="display:block; font-size:11px;">
              Forces this Global / Team dashboard onto the left-hand Dashboards menu for all users in scope (cannot be removed while enabled).
            </span>
          </span>
        </label>
      </div>
      <div>
        <label class="chip-option" style="width:100%;">
          <input type="checkbox" id="mdp-user-default" ${
            dash.is_user_default ? "checked" : ""
          } />
          <span>
            <strong>&#9733; Set as My Default Dashboard (${esc(currentUser.username)})</strong>
            <span class="text-muted" style="display:block; font-size:11px;">
              Loads this dashboard automatically when you visit <code>/dashboard</code>.
            </span>
          </span>
        </label>
      </div>
      <div id="mdp-global-default-wrap" ${
        dash.scope === "GLOBAL" && hasPermission("GLOBAL_ADMIN") ? "" : "hidden"
      }>
        <label class="chip-option" style="width:100%;">
          <input type="checkbox" id="mdp-global-default" ${
            dash.is_global_default ? "checked" : ""
          } />
          <span>
            <strong>&#127760; Set as App-Wide Default Global Dashboard</strong>
            <span class="text-muted" style="display:block; font-size:11px;">
              System-wide default dashboard for all users who have not set a personal default override.
            </span>
          </span>
        </label>
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: "Save Properties",
          className: "btn btn--primary",
          onClick: async () => {
            const title = document.getElementById("mdp-title").value.trim();
            const description = document.getElementById("mdp-desc").value.trim();
            const scope = document.getElementById("mdp-scope").value;
            const alwaysEl = document.getElementById("mdp-always-display");
            const userDefEl = document.getElementById("mdp-user-default");
            const globalDefEl = document.getElementById("mdp-global-default");
            const alwaysDisplay =
              (scope === "GLOBAL" || scope === "TEAM") && Boolean(alwaysEl && alwaysEl.checked);
            const setAsUserDefault = Boolean(userDefEl && userDefEl.checked);
            const setAsGlobalDefault =
              scope === "GLOBAL" && Boolean(globalDefEl && globalDefEl.checked);

            if (!title) {
              showToast("Validation Error", "Dashboard Name is required", "error");
              return;
            }
            const teamIds =
              scope === "TEAM"
                ? Array.from(document.querySelectorAll("input[name='mdp-team-cb']:checked")).map(
                    (el) => el.value
                  )
                : [];
            if (scope === "TEAM" && teamIds.length === 0) {
              showToast("Validation Error", "Select at least 1 Team for Team scope", "error");
              return;
            }

            try {
              const res = await apiRequest("/api/v1/dashboards", "POST", {
                action: "update_properties",
                dashboard_id: dash.id,
                title,
                description,
                scope,
                team_ids: teamIds,
                owner_usernames: scope === "PERSONAL" ? [currentUser.username] : [],
                always_display: alwaysDisplay,
                set_as_user_default: setAsUserDefault,
                set_as_global_default: setAsGlobalDefault,
              });
              appState.snapshot = res.state;
              if (appState.editMode && appState.workingDashboard && appState.workingDashboard.id === dash.id) {
                appState.workingDashboard.title = title;
                appState.workingDashboard.description = description;
                appState.workingDashboard.scope = scope;
                appState.workingDashboard.team_ids = teamIds;
                appState.workingDashboard.always_display = alwaysDisplay;
              }
              closeModal();
              renderAll();
              showToast(
                "Dashboard Properties Updated",
                `${title} (${formatScopeLabel(scope)}${alwaysDisplay ? ", Always Display" : ""})`,
                "ok"
              );
            } catch (err) {
              showToast("Failed to Update Properties", err.message, "error");
            }
          },
        },
      ]
    );

    const scopeSel = document.getElementById("mdp-scope");
    const teamsWrap = document.getElementById("mdp-teams-wrap");
    const alwaysWrap = document.getElementById("mdp-always-display-wrap");
    const globalDefWrap = document.getElementById("mdp-global-default-wrap");
    if (scopeSel) {
      scopeSel.addEventListener("change", () => {
        if (teamsWrap) teamsWrap.hidden = scopeSel.value !== "TEAM";
        if (alwaysWrap) {
          alwaysWrap.hidden = scopeSel.value !== "GLOBAL" && scopeSel.value !== "TEAM";
        }
        if (globalDefWrap) {
          globalDefWrap.hidden =
            scopeSel.value !== "GLOBAL" || !hasPermission("GLOBAL_ADMIN");
        }
      });
    }
  }

  async function addExistingDashboardToMenu(dashId) {
    try {
      const res = await apiRequest("/api/v1/dashboards", "POST", {
        action: "add_existing",
        dashboard_id: dashId,
      });
      appState.snapshot = res.state;
      appState.activeDashboardId = res.added_dashboard_id || dashId;
      appState.currentView = "dashboard";
      closeModal();
      renderAll();
      showToast("Dashboard Added to Menu", "Pinned Global/Team dashboard to your left rail", "ok");
    } catch (err) {
      showToast("Error Adding Dashboard", err.message, "error");
    }
  }

  function openCreateDashboardModal() {
    openDashboardMenuPopup("create_new");
  }

  /* ------------------------------------------------------------------ Endpoint Lists Screen (/lists) — 2 Cards (Global/Team & Personal) */

  function renderListsView(container) {
    const allLists = appState.snapshot.lists || [];
    const visibleLists = allLists.filter((l) => {
      if (appState.listFilterScope !== "ALL" && l.scope !== appState.listFilterScope) return false;
      return true;
    });

    const globalTeamLists = visibleLists.filter(
      (l) => l.scope === "GLOBAL" || l.scope === "TEAM"
    );
    const personalLists = visibleLists.filter((l) => l.scope === "PERSONAL");
    const canWriteShared = canWriteScope("GLOBAL") || canWriteScope("TEAM");

    const globalTeamHtml =
      globalTeamLists.length === 0
        ? `<div class="text-muted" style="padding:16px; text-align:center;">No Global or Team lists match the current filter.</div>`
        : globalTeamLists
            .map(
              (lst) => `
              <div class="list-subpanel">
                ${renderListCardInner(lst, null, true)}
              </div>
            `
            )
            .join("");

    const personalHtml =
      personalLists.length === 0
        ? `<div class="text-muted" style="padding:16px; text-align:center;">No Personal lists match the current filter.</div>`
        : personalLists
            .map(
              (lst) => `
              <div class="list-subpanel">
                ${renderListCardInner(lst, null, true)}
              </div>
            `
            )
            .join("");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>Resources &amp; Lists</span>
          <span>/</span>
          <span>Endpoint Lists</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#9776;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">
              Endpoint Lists
              <span class="ws-badge tone-brand tabular">${visibleLists.length} Lists</span>
            </h1>
            <div class="page-header__caption">
              Define reusable lists of hosts (e.g., Routers, Operations Portals) separated into Global/Team Lists and Personal Lists. Lists can only contain Catalog items with the exact same scope.
            </div>
          </div>
          <div class="page-header__actions">
            <select id="list-scope-filter" class="select" style="width:auto;">
              <option value="ALL" ${
                appState.listFilterScope === "ALL" ? "selected" : ""
              }>All Scopes</option>
              <option value="GLOBAL" ${
                appState.listFilterScope === "GLOBAL" ? "selected" : ""
              }>Global Lists</option>
              <option value="TEAM" ${
                appState.listFilterScope === "TEAM" ? "selected" : ""
              }>Team Lists</option>
              <option value="PERSONAL" ${
                appState.listFilterScope === "PERSONAL" ? "selected" : ""
              }>Personal Lists</option>
            </select>
            <button type="button" class="btn btn--primary" id="btn-create-list">+ Define New List</button>
          </div>
        </div>
      </header>

      <!-- Card 1: Global & Team Endpoint Lists -->
      <section class="page-card" id="lists-card-global-team" style="margin-bottom:20px;">
        <header class="page-card__head">
          <div class="page-card__titles">
            <h2 class="page-card__title">
              <span>&#127760; Global &amp; Team Endpoint Lists</span>
              <span class="ws-badge tone-brand tabular">${globalTeamLists.length}</span>
            </h2>
            <div class="page-card__caption">Shared lists visible across Global and Team scopes</div>
          </div>
          <div class="page-card__actions">
            ${
              canWriteShared
                ? `<button type="button" class="btn btn--sm btn--primary" id="btn-create-shared-list">+ Define Global / Team List</button>`
                : ""
            }
          </div>
        </header>
        <div class="page-card__body">
          ${globalTeamHtml}
        </div>
      </section>

      <!-- Card 2: Personal Endpoint Lists -->
      <section class="page-card" id="lists-card-personal">
        <header class="page-card__head">
          <div class="page-card__titles">
            <h2 class="page-card__title">
              <span>&#128100; Personal Endpoint Lists</span>
              <span class="ws-badge tone-stale tabular">${personalLists.length}</span>
            </h2>
            <div class="page-card__caption">Individual operator lists scoped to ${esc(
              getCurrentUser().username
            )}</div>
          </div>
          <div class="page-card__actions">
            <button type="button" class="btn btn--sm btn--primary" id="btn-create-personal-list">+ Define Personal List</button>
          </div>
        </header>
        <div class="page-card__body">
          ${personalHtml}
        </div>
      </section>
    `;

    const scopeFilter = document.getElementById("list-scope-filter");
    if (scopeFilter) {
      scopeFilter.addEventListener("change", () => {
        appState.listFilterScope = scopeFilter.value;
        renderListsView(container);
      });
    }

    const createBtn = document.getElementById("btn-create-list");
    if (createBtn) {
      createBtn.addEventListener("click", () => openListModal(null));
    }

    const createSharedBtn = document.getElementById("btn-create-shared-list");
    if (createSharedBtn) {
      createSharedBtn.addEventListener("click", () =>
        openListModal(null, canWriteScope("GLOBAL") ? "GLOBAL" : "TEAM")
      );
    }

    const createPersBtn = document.getElementById("btn-create-personal-list");
    if (createPersBtn) {
      createPersBtn.addEventListener("click", () => openListModal(null, "PERSONAL"));
    }

  }

  function openListModal(existingList = null, preferredScope = null) {
    const teams = appState.snapshot.teams || [];
    const catalog = appState.snapshot.catalog || [];
    const currentUser = getCurrentUser();
    const canGlobal = canWriteScope("GLOBAL");
    const canTeam = canWriteScope("TEAM");

    const initialScope = existingList
      ? existingList.scope
      : preferredScope
      ? preferredScope
      : canGlobal
      ? "GLOBAL"
      : canTeam
      ? "TEAM"
      : "PERSONAL";

    const selectedTeamIds = new Set(
      existingList ? existingList.team_ids || [] : currentUser.team_ids || []
    );
    let orderedItemIds = existingList ? [...(existingList.item_ids || [])] : [];
    const selectedItemIds = new Set(orderedItemIds);

    openModal(
      existingList ? `Edit List — ${existingList.title}` : "Define Endpoint List",
      `
      <div>
        <label class="field-label">List Title (e.g., Routers)</label>
        <input type="text" id="ml-title" class="input" placeholder="e.g., Routers" value="${esc(
          existingList ? existingList.title : ""
        )}" />
      </div>
      <div>
        <label class="field-label">Description</label>
        <input type="text" id="ml-desc" class="input" placeholder="Optional description" value="${esc(
          existingList ? existingList.description : ""
        )}" />
      </div>
      <div>
        <label class="field-label">List Scope [Global, Team(s), Personal]</label>
        <select id="ml-scope" class="select">
          <option value="GLOBAL" ${initialScope === "GLOBAL" ? "selected" : ""} ${
        !canGlobal ? "disabled" : ""
      }>Global ${!canGlobal ? "— Requires Can Add Global permission" : ""}</option>
          <option value="TEAM" ${initialScope === "TEAM" ? "selected" : ""} ${
        !canTeam ? "disabled" : ""
      }>Team(s) ${!canTeam ? "— Requires Can Add Team permission" : ""}</option>
          <option value="PERSONAL" ${
            initialScope === "PERSONAL" ? "selected" : ""
          }>Personal (${esc(currentUser.username)})</option>
        </select>
      </div>
      <div id="ml-teams-wrap" ${initialScope === "TEAM" ? "" : "hidden"}>
        <label class="field-label">Assigned Team(s)</label>
        <div class="chip-select-grid">
          ${teams
            .map(
              (t) => `
            <label class="chip-option">
              <input type="checkbox" name="ml-team-cb" value="${esc(t.id)}" ${
                selectedTeamIds.has(t.id) ? "checked" : ""
              } />
              <span class="mono" style="font-weight:600;">${esc(t.code)}</span>
              <span class="text-muted">${esc(t.name)}</span>
            </label>
          `
            )
            .join("")}
        </div>
      </div>
      <div>
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
          <label class="field-label" style="margin:0;">Select &amp; Drag to Order Catalog Items (Same-Scope Rule)</label>
          <span class="ws-badge tone-brand" id="ml-scope-rule-pill">Showing ${esc(
            formatScopeLabel(initialScope)
          )} items only</span>
        </div>
        <div class="chip-select-grid" id="ml-items-container" style="flex-direction:column; align-items:stretch;"></div>
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: existingList ? "Save List" : "Create List",
          className: "btn btn--primary",
          onClick: async () => {
            const title = document.getElementById("ml-title").value.trim();
            const description = document.getElementById("ml-desc").value.trim();
            const scope = document.getElementById("ml-scope").value;
            if (!title) {
              showToast("Validation Error", "List Title is required", "error");
              return;
            }
            const teamIds =
              scope === "TEAM"
                ? Array.from(document.querySelectorAll("input[name='ml-team-cb']:checked")).map(
                    (el) => el.value
                  )
                : [];
            if (scope === "TEAM" && teamIds.length === 0) {
              showToast("Validation Error", "Select at least 1 team for a Team list", "error");
              return;
            }
            const itemIds = Array.from(
              document.querySelectorAll("input[name='ml-item-cb']:checked")
            ).map((el) => el.value);

            try {
              appState.snapshot = await apiRequest("/api/v1/lists", "POST", {
                action: "save",
                id: existingList ? existingList.id : undefined,
                title,
                description,
                scope,
                team_ids: teamIds,
                owner_usernames: scope === "PERSONAL" ? [currentUser.username] : [],
                item_ids: itemIds,
              });
              closeModal();
              renderAll();
              showToast(
                existingList ? "List Updated" : "List Created",
                `${title} (${formatScopeLabel(scope)})`,
                "ok"
              );
            } catch (err) {
              showToast("Could Not Save List", err.message, "error");
            }
          },
        },
      ]
    );

    const scopeSel = document.getElementById("ml-scope");
    const teamsWrap = document.getElementById("ml-teams-wrap");
    const itemsContainer = document.getElementById("ml-items-container");
    const rulePill = document.getElementById("ml-scope-rule-pill");

    function renderEligibleItems() {
      const activeScope = scopeSel.value;
      teamsWrap.hidden = activeScope !== "TEAM";
      rulePill.textContent = `Showing ${formatScopeLabel(activeScope)} items only`;

      const eligible = catalog.filter((item) => item.scope === activeScope);
      if (eligible.length === 0) {
        itemsContainer.innerHTML = `<div class="text-muted" style="padding:8px;">No Catalog items exist with scope <strong>${esc(
          formatScopeLabel(activeScope)
        )}</strong> yet. Add one in the Catalog screen first.</div>`;
        return;
      }

      // Sort so already-selected items appear in their saved order first, followed by unselected items
      const orderedEligible = [...eligible].sort((a, b) => {
        const idxA = orderedItemIds.indexOf(a.id);
        const idxB = orderedItemIds.indexOf(b.id);
        if (idxA !== -1 && idxB !== -1) return idxA - idxB;
        if (idxA !== -1) return -1;
        if (idxB !== -1) return 1;
        return 0;
      });
      orderedItemIds = orderedEligible.map((it) => it.id);

      itemsContainer.innerHTML = orderedEligible
        .map(
          (item, idx) => `
          <label class="chip-option draggable-row" draggable="true" data-modal-item-idx="${idx}" data-modal-item-id="${esc(
            item.id
          )}" style="justify-content:space-between;">
            <span style="display:flex; align-items:center; gap:8px; min-width:0;">
              <span class="drag-handle" title="Drag to reorder item">&#10495;</span>
              <input type="checkbox" name="ml-item-cb" value="${esc(item.id)}" ${
            selectedItemIds.has(item.id) ? "checked" : ""
          } />
              ${renderProtocolBadge(item.protocol)}
              <span style="font-weight:600;">${esc(item.title)}</span>
              <span class="mono text-muted">${esc(formatHostDisplay(item))}</span>
            </span>
            <span style="display:flex; align-items:center; gap:4px;">
              <span class="ws-badge tone-offline mono">${esc(item.site || "2SYA")}</span>
              ${renderScopeBadge(item.scope, item.team_ids, item.owner_usernames)}
            </span>
          </label>
        `
        )
        .join("");

      itemsContainer.querySelectorAll("input[name='ml-item-cb']").forEach((cb) => {
        cb.addEventListener("change", () => {
          if (cb.checked) selectedItemIds.add(cb.value);
          else selectedItemIds.delete(cb.value);
        });
      });

      let dragModalIdx = null;
      itemsContainer.querySelectorAll("[data-modal-item-idx]").forEach((rowEl) => {
        rowEl.addEventListener("dragstart", (ev) => {
          dragModalIdx = Number(rowEl.getAttribute("data-modal-item-idx"));
          rowEl.classList.add("draggable-row--dragging");
          if (ev.dataTransfer) {
            ev.dataTransfer.effectAllowed = "move";
            ev.dataTransfer.setData("text/plain", String(dragModalIdx));
          }
        });
        rowEl.addEventListener("dragend", () => {
          dragModalIdx = null;
          rowEl.classList.remove("draggable-row--dragging");
          itemsContainer.querySelectorAll(".draggable-row--over").forEach((el) => {
            el.classList.remove("draggable-row--over");
          });
        });
        rowEl.addEventListener("dragover", (ev) => {
          if (dragModalIdx === null) return;
          const targetIdx = Number(rowEl.getAttribute("data-modal-item-idx"));
          if (targetIdx === dragModalIdx) return;
          ev.preventDefault();
          rowEl.classList.add("draggable-row--over");
        });
        rowEl.addEventListener("dragleave", () => {
          rowEl.classList.remove("draggable-row--over");
        });
        rowEl.addEventListener("drop", (ev) => {
          if (dragModalIdx === null) return;
          const targetIdx = Number(rowEl.getAttribute("data-modal-item-idx"));
          rowEl.classList.remove("draggable-row--over");
          if (targetIdx === dragModalIdx) return;
          ev.preventDefault();
          const [movedId] = orderedItemIds.splice(dragModalIdx, 1);
          orderedItemIds.splice(targetIdx, 0, movedId);
          dragModalIdx = null;
          renderEligibleItems();
        });
      });
    }

    scopeSel.addEventListener("change", () => {
      selectedItemIds.clear();
      orderedItemIds = [];
      renderEligibleItems();
    });
    renderEligibleItems();
  }

  /* ------------------------------------------------------------------ Catalog Screen (/catalog) — 2 Cards (Global/Team & Personal) */

  function renderCatalogRows(items, emptyMessage) {
    if (!items || items.length === 0) {
      return `<tr><td colspan="7" class="text-muted" style="text-align:center; padding:20px;">${esc(
        emptyMessage
      )}</td></tr>`;
    }
    return items
      .map((item) => {
        const canEdit = canWriteScope(item.scope);
        return `
        <tr>
          <td>${renderProtocolBadge(item.protocol)}</td>
          <td>
            <div style="font-weight:600;">${esc(item.title)}</div>
            <div class="text-muted" style="font-size:11px;">${esc(item.description)}</div>
          </td>
          <td class="mono">${esc(formatHostDisplay(item))}</td>
          <td><span class="ws-badge tone-offline mono">${esc(item.site || "2SYA")}</span></td>
          <td>${renderZoneBadges(item.zone_ids)}</td>
          <td>${renderScopeBadge(item.scope, item.team_ids, item.owner_usernames)}</td>
          <td style="text-align:right; white-space:nowrap;">
            ${renderLaunchButton(item, "btn--sm")}
            ${
              canEdit
                ? `<button type="button" class="btn btn--sm btn--ghost" data-edit-catalog="${esc(
                    item.id
                  )}" title="Edit item">&#9998;</button>
                   <button type="button" class="btn btn--sm btn--danger" data-delete-catalog="${esc(
                     item.id
                   )}" title="Delete item">&#128465;</button>`
                : ""
            }
          </td>
        </tr>
      `;
      })
      .join("");
  }

  function renderCatalogView(container) {
    const allItems = appState.snapshot.catalog || [];
    const q = (appState.catalogSearch || "").trim().toLowerCase();

    const filtered = allItems.filter((item) => {
      if (
        appState.catalogFilterProtocol !== "ALL" &&
        item.protocol !== appState.catalogFilterProtocol
      ) {
        return false;
      }
      if (appState.catalogFilterScope !== "ALL" && item.scope !== appState.catalogFilterScope) {
        return false;
      }
      if (q) {
        const hay = `${item.title} ${item.host} ${item.site || ""} ${(item.tags || []).join(
          " "
        )}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const globalTeamItems = filtered.filter(
      (item) => item.scope === "GLOBAL" || item.scope === "TEAM"
    );
    const personalItems = filtered.filter((item) => item.scope === "PERSONAL");
    const canWriteShared = canWriteScope("GLOBAL") || canWriteScope("TEAM");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>Resources &amp; Lists</span>
          <span>/</span>
          <span>Catalog Items</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#128218;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">
              Catalog Items
              <span class="ws-badge tone-brand tabular">${filtered.length} Items</span>
            </h1>
            <div class="page-header__caption">
              Add endpoints with Site Code, Zone restrictions (1 or more IP CIDR zones), and Scope restrictions separated into Global/Team Items and Personal Items.
            </div>
          </div>
          <div class="page-header__actions">
            <input type="text" id="cat-search-input" class="input" style="width:240px;" placeholder="Filter hostname, site (2SYA), tag..." value="${esc(
              appState.catalogSearch
            )}" />
            <select id="cat-proto-filter" class="select" style="width:auto;">
              <option value="ALL" ${
                appState.catalogFilterProtocol === "ALL" ? "selected" : ""
              }>All Protocols</option>
              <option value="WEB" ${
                appState.catalogFilterProtocol === "WEB" ? "selected" : ""
              }>WEB</option>
              <option value="SSH" ${
                appState.catalogFilterProtocol === "SSH" ? "selected" : ""
              }>SSH</option>
              <option value="RDP" ${
                appState.catalogFilterProtocol === "RDP" ? "selected" : ""
              }>RDP</option>
              <option value="LOCAL_APP" ${
                appState.catalogFilterProtocol === "LOCAL_APP" ? "selected" : ""
              }>LOCAL_APP</option>
            </select>
            <select id="cat-scope-filter" class="select" style="width:auto;">
              <option value="ALL" ${
                appState.catalogFilterScope === "ALL" ? "selected" : ""
              }>All Types (Scopes)</option>
              <option value="GLOBAL" ${
                appState.catalogFilterScope === "GLOBAL" ? "selected" : ""
              }>Type = Global</option>
              <option value="TEAM" ${
                appState.catalogFilterScope === "TEAM" ? "selected" : ""
              }>Type = Team</option>
              <option value="PERSONAL" ${
                appState.catalogFilterScope === "PERSONAL" ? "selected" : ""
              }>Type = Personal</option>
            </select>
            <button type="button" class="btn btn--primary" id="btn-add-catalog">+ Add Item to Catalog</button>
          </div>
        </div>
      </header>

      <!-- Card 1: Global & Team Catalog Items -->
      <section class="page-card" id="catalog-card-global-team" style="margin-bottom:20px;">
        <header class="page-card__head">
          <div class="page-card__titles">
            <h2 class="page-card__title">
              <span>&#127760; Global &amp; Team Catalog Items</span>
              <span class="ws-badge tone-brand tabular">${globalTeamItems.length}</span>
            </h2>
            <div class="page-card__caption">Shared endpoints available across Global and Team scopes</div>
          </div>
          <div class="page-card__actions">
            ${
              canWriteShared
                ? `<button type="button" class="btn btn--sm btn--primary" id="btn-add-catalog-shared">+ Add Global / Team Item</button>`
                : ""
            }
          </div>
        </header>
        <div class="page-card__body page-card__body--flush" style="overflow-x:auto;">
          <table class="ws-table">
            <thead>
              <tr>
                <th>Type+Icon</th>
                <th>Title &amp; Description</th>
                <th>Target (Host / URL / Command)</th>
                <th>Site</th>
                <th>Zone(s)</th>
                <th>Type (Scope)</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${renderCatalogRows(globalTeamItems, "No Global or Team catalog items match your filters.")}
            </tbody>
          </table>
        </div>
      </section>

      <!-- Card 2: Personal Catalog Items -->
      <section class="page-card" id="catalog-card-personal">
        <header class="page-card__head">
          <div class="page-card__titles">
            <h2 class="page-card__title">
              <span>&#128100; Personal Catalog Items</span>
              <span class="ws-badge tone-stale tabular">${personalItems.length}</span>
            </h2>
            <div class="page-card__caption">Personal endpoints scoped to ${esc(
              getCurrentUser().username
            )}</div>
          </div>
          <div class="page-card__actions">
            <button type="button" class="btn btn--sm btn--primary" id="btn-add-catalog-personal">+ Add Personal Item</button>
          </div>
        </header>
        <div class="page-card__body page-card__body--flush" style="overflow-x:auto;">
          <table class="ws-table">
            <thead>
              <tr>
                <th>Type+Icon</th>
                <th>Title &amp; Description</th>
                <th>Target (Host / URL / Command)</th>
                <th>Site</th>
                <th>Zone(s)</th>
                <th>Type (Scope)</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${renderCatalogRows(personalItems, "No Personal catalog items match your filters.")}
            </tbody>
          </table>
        </div>
      </section>
    `;

    const searchInput = document.getElementById("cat-search-input");
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        appState.catalogSearch = searchInput.value;
        renderCatalogView(container);
        const refocused = document.getElementById("cat-search-input");
        if (refocused) {
          refocused.focus();
          refocused.setSelectionRange(refocused.value.length, refocused.value.length);
        }
      });
    }

    const protoFilter = document.getElementById("cat-proto-filter");
    if (protoFilter) {
      protoFilter.addEventListener("change", () => {
        appState.catalogFilterProtocol = protoFilter.value;
        renderCatalogView(container);
      });
    }

    const scopeFilter = document.getElementById("cat-scope-filter");
    if (scopeFilter) {
      scopeFilter.addEventListener("change", () => {
        appState.catalogFilterScope = scopeFilter.value;
        renderCatalogView(container);
      });
    }

    const addBtn = document.getElementById("btn-add-catalog");
    if (addBtn) {
      addBtn.addEventListener("click", () => openCatalogItemModal(null));
    }

    const addSharedBtn = document.getElementById("btn-add-catalog-shared");
    if (addSharedBtn) {
      addSharedBtn.addEventListener("click", () =>
        openCatalogItemModal(null, canWriteScope("GLOBAL") ? "GLOBAL" : "TEAM")
      );
    }

    const addPersonalBtn = document.getElementById("btn-add-catalog-personal");
    if (addPersonalBtn) {
      addPersonalBtn.addEventListener("click", () => openCatalogItemModal(null, "PERSONAL"));
    }
  }

  function openCatalogItemModal(existingItem = null, preferredScope = null) {
    const teams = appState.snapshot.teams || [];
    const zones = appState.snapshot.zones || [];
    const sites = appState.snapshot.sites || [];
    const currentUser = getCurrentUser();
    const canGlobal = canWriteScope("GLOBAL");
    const canTeam = canWriteScope("TEAM");

    const initialScope = existingItem
      ? existingItem.scope
      : preferredScope
      ? preferredScope
      : canGlobal
      ? "GLOBAL"
      : canTeam
      ? "TEAM"
      : "PERSONAL";

    const initialProtocol = existingItem ? existingItem.protocol : "SSH";
    const initialSite = existingItem && existingItem.site ? existingItem.site : sites[0] ? sites[0].code : "2SYA";
    const siteOptions = [...sites];
    if (
      initialSite &&
      !siteOptions.some((s) => (s.code || "").toUpperCase() === initialSite.toUpperCase())
    ) {
      siteOptions.push({
        id: "site-custom",
        code: initialSite.toUpperCase(),
        name: "Custom Site",
        description: "",
      });
    }

    const selectedTeamIds = new Set(
      existingItem ? existingItem.team_ids || [] : currentUser.team_ids || []
    );
    const selectedZoneIds = new Set(existingItem ? existingItem.zone_ids || [] : []);

    openModal(
      existingItem ? `Edit Catalog Item — ${existingItem.title}` : "Add Item to Catalog",
      `
      <div style="display:grid; grid-template-columns: 1fr 2fr; gap:12px;">
        <div>
          <label class="field-label">Type + Icon (Protocol)</label>
          <select id="mc-protocol" class="select">
            <option value="WEB" ${
              initialProtocol === "WEB" ? "selected" : ""
            }>&#127760; WEB (URL)</option>
            <option value="SSH" ${
              initialProtocol === "SSH" ? "selected" : ""
            }>&gt;_ SSH (Host / Port)</option>
            <option value="RDP" ${
              initialProtocol === "RDP" ? "selected" : ""
            }>&#128421; RDP (Host / Port 3389)</option>
            <option value="LOCAL_APP" ${
              initialProtocol === "LOCAL_APP" ? "selected" : ""
            }>&#9889; LOCAL_APP (Command &amp; Args)</option>
          </select>
        </div>
        <div>
          <label class="field-label">Display Title</label>
          <input type="text" id="mc-title" class="input" placeholder="e.g., Core Edge Router 01 (2SYA)" value="${esc(
            existingItem ? existingItem.title : ""
          )}" />
        </div>
      </div>

      <!-- Protocol-Aware Target Fields -->
      <div id="mc-target-grid" style="display:grid; grid-template-columns: 2fr 1fr 1fr; gap:12px;">
        <div id="mc-host-wrap">
          <label class="field-label" id="mc-host-label">Host / IP Address</label>
          <input type="text" id="mc-host" class="input mono" placeholder="router1.network.example.com" value="${esc(
            existingItem ? existingItem.host : ""
          )}" />
        </div>
        <div id="mc-port-wrap">
          <label class="field-label" id="mc-port-label">Port</label>
          <input type="number" id="mc-port" class="input mono" placeholder="22" value="${esc(
            existingItem && existingItem.port
              ? existingItem.port
              : initialProtocol === "RDP"
              ? 3389
              : initialProtocol === "SSH"
              ? 22
              : ""
          )}" />
        </div>
        <div id="mc-site-wrap">
          <div style="display:flex; align-items:center; justify-content:space-between;">
            <label class="field-label" style="margin-bottom:4px;">Pre-Defined Site</label>
            <button type="button" class="btn btn--ghost btn--sm" id="btn-modal-manage-sites" style="height:18px; padding:0 4px; font-size:11px;" title="Open Pre-Defined Sites Screen">Edit Sites &rarr;</button>
          </div>
          <select id="mc-site" class="select mono">
            ${siteOptions
              .map(
                (s) => `
              <option value="${esc(s.code)}" ${
                  s.code.toUpperCase() === initialSite.toUpperCase() ? "selected" : ""
                }>${esc(s.code)} — ${esc(s.name)}</option>
            `
              )
              .join("")}
          </select>
        </div>
      </div>

      <div id="mc-args-wrap" hidden>
        <label class="field-label" id="mc-args-label">Command Line Options / Arguments</label>
        <input type="text" id="mc-args" class="input mono" placeholder="--profile dmz-tap-capture --user {user}" value="${esc(
          existingItem ? existingItem.path_or_args || "" : ""
        )}" />
      </div>

      <div id="mc-account-wrap" hidden>
        <label class="field-label" id="mc-account-label">Remote Username Override (Optional)</label>
        <input type="text" id="mc-account" class="input mono" placeholder="Leave blank to use profile default" value="${esc(
          existingItem ? existingItem.account_override || "" : ""
        )}" />
      </div>

      <div>
        <label class="field-label">Restrictions — Item Scope (Type)</label>
        <select id="mc-scope" class="select">
          <option value="GLOBAL" ${initialScope === "GLOBAL" ? "selected" : ""} ${
        !canGlobal ? "disabled" : ""
      }>No restrictions (Type = Global) ${
        !canGlobal ? "— Requires Can Add Global permission" : ""
      }</option>
          <option value="TEAM" ${initialScope === "TEAM" ? "selected" : ""} ${
        !canTeam ? "disabled" : ""
      }>1 or more Teams (Type = Team) ${
        !canTeam ? "— Requires Can Add Team permission" : ""
      }</option>
          <option value="PERSONAL" ${
            initialScope === "PERSONAL" ? "selected" : ""
          }>Individual / Personal (Type = Personal — ${esc(currentUser.username)})</option>
        </select>
      </div>

      <div id="mc-teams-wrap" ${initialScope === "TEAM" ? "" : "hidden"}>
        <label class="field-label">Select 1 or more Teams</label>
        <div class="chip-select-grid">
          ${teams
            .map(
              (t) => `
            <label class="chip-option">
              <input type="checkbox" name="mc-team-cb" value="${esc(t.id)}" ${
                selectedTeamIds.has(t.id) ? "checked" : ""
              } />
              <span class="mono" style="font-weight:600;">${esc(t.code)}</span>
              <span class="text-muted">${esc(t.name)}</span>
            </label>
          `
            )
            .join("")}
        </div>
      </div>

      <div>
        <label class="field-label">Zone(s) (Select 1 or more Security Zones, or leave unchecked for All Zones)</label>
        <div class="chip-select-grid">
          ${zones
            .map(
              (z) => `
            <label class="chip-option">
              <input type="checkbox" name="mc-zone-cb" value="${esc(z.id)}" ${
                selectedZoneIds.has(z.id) ? "checked" : ""
              } />
              <span style="font-weight:600;">${esc(z.name)}</span>
              <span class="mono text-muted" style="font-size:11px;">(${(z.cidrs || []).join(
                ", "
              )})</span>
            </label>
          `
            )
            .join("")}
        </div>
      </div>

      <div>
        <label class="field-label">Description (Optional)</label>
        <input type="text" id="mc-desc" class="input" placeholder="Notes on purpose or platform" value="${esc(
          existingItem ? existingItem.description : ""
        )}" />
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: existingItem ? "Save Changes" : "Add to Catalog",
          className: "btn btn--primary",
          onClick: async () => {
            const protocol = document.getElementById("mc-protocol").value;
            const title = document.getElementById("mc-title").value.trim();
            const host = document.getElementById("mc-host").value.trim();
            const portRaw = document.getElementById("mc-port").value.trim();
            const site = document.getElementById("mc-site").value.trim().toUpperCase() || "2SYA";
            const pathOrArgs = document.getElementById("mc-args").value.trim();
            const accountOverride = document.getElementById("mc-account").value.trim();
            const scope = document.getElementById("mc-scope").value;
            const description = document.getElementById("mc-desc").value.trim();

            if (!title || !host) {
              const targetFieldName =
                protocol === "WEB"
                  ? "Target URL"
                  : protocol === "LOCAL_APP"
                  ? "Command / Executable"
                  : "Host / IP";
              showToast("Validation Error", `Title and ${targetFieldName} are required`, "error");
              return;
            }
            const teamIds =
              scope === "TEAM"
                ? Array.from(document.querySelectorAll("input[name='mc-team-cb']:checked")).map(
                    (el) => el.value
                  )
                : [];
            if (scope === "TEAM" && teamIds.length === 0) {
              showToast("Validation Error", "Select at least 1 Team when Type = Team", "error");
              return;
            }
            const zoneIds = Array.from(
              document.querySelectorAll("input[name='mc-zone-cb']:checked")
            ).map((el) => el.value);

            let resolvedPort = null;
            if (protocol === "SSH" || protocol === "RDP") {
              resolvedPort = portRaw
                ? Number(portRaw)
                : protocol === "RDP"
                ? 3389
                : 22;
            }

            try {
              const res = await apiRequest("/api/v1/catalog", "POST", {
                action: "create",
                id: existingItem ? existingItem.id : undefined,
                title,
                description,
                protocol,
                host,
                port: resolvedPort,
                site,
                path_or_args:
                  protocol === "LOCAL_APP" || protocol === "SSH" ? pathOrArgs : "",
                account_override:
                  protocol === "SSH" || protocol === "RDP" ? accountOverride : "",
                scope,
                team_ids: teamIds,
                owner_usernames: scope === "PERSONAL" ? [currentUser.username] : [],
                zone_ids: zoneIds,
              });
              appState.snapshot = res.state;
              closeModal();
              renderAll();
              showToast(
                existingItem ? "Catalog Item Updated" : "Catalog Item Added",
                `${title} (${host})`,
                "ok"
              );
            } catch (err) {
              showToast("Catalog Error", err.message, "error");
            }
          },
        },
      ]
    );

    const protoSel = document.getElementById("mc-protocol");
    const targetGrid = document.getElementById("mc-target-grid");
    const hostLabel = document.getElementById("mc-host-label");
    const hostInput = document.getElementById("mc-host");
    const portWrap = document.getElementById("mc-port-wrap");
    const portLabel = document.getElementById("mc-port-label");
    const portInput = document.getElementById("mc-port");
    const argsWrap = document.getElementById("mc-args-wrap");
    const argsLabel = document.getElementById("mc-args-label");
    const argsInput = document.getElementById("mc-args");
    const accountWrap = document.getElementById("mc-account-wrap");
    const accountLabel = document.getElementById("mc-account-label");
    const accountInput = document.getElementById("mc-account");

    function updateProtocolFields() {
      const proto = protoSel ? protoSel.value : "SSH";
      if (proto === "WEB") {
        // URL + Site (no Port, no CLI args)
        if (targetGrid) targetGrid.style.gridTemplateColumns = "2.5fr 1fr";
        if (hostLabel) hostLabel.textContent = "Target URL (HTTPS / HTTP)";
        if (hostInput) hostInput.placeholder = "https://reference-app.int.example.net/health";
        if (portWrap) portWrap.hidden = true;
        if (argsWrap) argsWrap.hidden = true;
        if (accountWrap) accountWrap.hidden = true;
      } else if (proto === "LOCAL_APP") {
        // Command + Command Line Options (no Host/Port!)
        if (targetGrid) targetGrid.style.gridTemplateColumns = "2.5fr 1fr";
        if (hostLabel) hostLabel.textContent = "Command / Executable Path";
        if (hostInput) hostInput.placeholder = "/opt/soe/bin/packet-workbench";
        if (portWrap) portWrap.hidden = true;
        if (argsWrap) argsWrap.hidden = false;
        if (argsLabel) argsLabel.textContent = "Command Line Options / Arguments";
        if (argsInput) argsInput.placeholder = "--profile dmz-tap-capture --user {user}";
        if (accountWrap) accountWrap.hidden = true;
      } else if (proto === "RDP") {
        // Host + Port (defaults to 3389) + Site
        if (targetGrid) targetGrid.style.gridTemplateColumns = "2fr 1fr 1fr";
        if (hostLabel) hostLabel.textContent = "Host / IP Address";
        if (hostInput) hostInput.placeholder = "jump01.ad.example.net";
        if (portWrap) portWrap.hidden = false;
        if (portLabel) portLabel.textContent = "RDP Port (Default 3389)";
        if (portInput) {
          portInput.placeholder = "3389";
          if (!portInput.value || portInput.value === "22") {
            portInput.value = "3389";
          }
        }
        if (argsWrap) argsWrap.hidden = true;
        if (accountWrap) accountWrap.hidden = false;
        if (accountLabel) accountLabel.textContent = "Domain\\Username Override (Optional)";
        if (accountInput) accountInput.placeholder = "CORP\\joperator";
      } else {
        // SSH: Host + Port (defaults to 22) + Site + SSH Flags
        if (targetGrid) targetGrid.style.gridTemplateColumns = "2fr 1fr 1fr";
        if (hostLabel) hostLabel.textContent = "Host / IP Address";
        if (hostInput) hostInput.placeholder = "router1.network.example.com";
        if (portWrap) portWrap.hidden = false;
        if (portLabel) portLabel.textContent = "SSH Port (Default 22)";
        if (portInput) {
          portInput.placeholder = "22";
          if (!portInput.value || portInput.value === "3389") {
            portInput.value = existingItem && existingItem.port ? String(existingItem.port) : "22";
          }
        }
        if (argsWrap) argsWrap.hidden = false;
        if (argsLabel) argsLabel.textContent = "SSH Command Line Options / Flags (Optional)";
        if (argsInput) argsInput.placeholder = "-o StrictHostKeyChecking=accept-new";
        if (accountWrap) accountWrap.hidden = false;
        if (accountLabel) accountLabel.textContent = "Remote SSH Username Override (Optional)";
        if (accountInput) accountInput.placeholder = "Leave blank to use profile default";
      }
    }

    if (protoSel) {
      protoSel.addEventListener("change", updateProtocolFields);
    }
    updateProtocolFields();

    const manageSitesBtn = document.getElementById("btn-modal-manage-sites");
    if (manageSitesBtn) {
      manageSitesBtn.addEventListener("click", () => {
        closeModal();
        appState.currentView = "sites";
        window.history.pushState({}, "", "/sites");
        renderAll();
      });
    }

    const scopeSel = document.getElementById("mc-scope");
    const teamsWrap = document.getElementById("mc-teams-wrap");
    if (scopeSel && teamsWrap) {
      scopeSel.addEventListener("change", () => {
        teamsWrap.hidden = scopeSel.value !== "TEAM";
      });
    }
  }

  /* ------------------------------------------------------------------ Pre-Defined Sites Screen (/sites) */

  function renderSitesView(container) {
    const sites = appState.snapshot.sites || [];
    const catalog = appState.snapshot.catalog || [];
    const isAdmin = hasPermission("GLOBAL_ADMIN");

    const rowsHtml =
      sites.length === 0
        ? `<tr><td colspan="5" class="text-muted" style="text-align:center; padding:18px;">No pre-defined sites configured.</td></tr>`
        : sites
            .map((s) => {
              const usedCount = catalog.filter(
                (c) => (c.site || "").toUpperCase() === (s.code || "").toUpperCase()
              ).length;
              return `
              <tr>
                <td><span class="ws-badge tone-brand mono">${esc(s.code)}</span></td>
                <td style="font-weight:600;">${esc(s.name)}</td>
                <td class="text-muted">${esc(s.description)}</td>
                <td><span class="ws-badge tone-offline tabular">${usedCount} ${
                usedCount === 1 ? "item" : "items"
              }</span></td>
                <td style="text-align:right; white-space:nowrap;">
                  ${
                    isAdmin
                      ? `<button type="button" class="btn btn--sm btn--ghost" data-edit-site="${esc(
                          s.id
                        )}">&#9998; Edit</button>
                         <button type="button" class="btn btn--sm btn--danger" data-delete-site="${esc(
                           s.id
                         )}">&#128465;</button>`
                      : ""
                  }
                </td>
              </tr>
            `;
            })
            .join("");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>Scope, Zones &amp; RBAC</span>
          <span>/</span>
          <span>Pre-Defined Sites</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#127970;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">
              Pre-Defined Sites
              <span class="ws-badge tone-brand tabular">${sites.length} Sites</span>
            </h1>
            <div class="page-header__caption">
              Manage the pre-defined list of data center and POP site codes (e.g., 2SYA, 3MEL, 4BNE, 1CBR) available when defining Catalog Items.
            </div>
          </div>
          <div class="page-header__actions">
            ${
              isAdmin
                ? `<button type="button" class="btn btn--primary" id="btn-new-site">+ Define Site</button>`
                : `<span class="ws-badge tone-offline">Global Admin required to edit Sites</span>`
            }
          </div>
        </div>
      </header>

      <section class="page-card">
        <div class="page-card__body page-card__body--flush" style="overflow-x:auto;">
          <table class="ws-table">
            <thead>
              <tr>
                <th>Site Code</th>
                <th>Site Name</th>
                <th>Description</th>
                <th>Catalog Items</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </section>
    `;

    const newSiteBtn = document.getElementById("btn-new-site");
    if (newSiteBtn) {
      newSiteBtn.addEventListener("click", () => openSiteModal(null));
    }
  }

  function openSiteModal(existingSite = null) {
    openModal(
      existingSite ? `Edit Site — ${existingSite.code}` : "Define Pre-Defined Site",
      `
      <div style="display:grid; grid-template-columns: 1fr 2fr; gap:12px;">
        <div>
          <label class="field-label">Site Code</label>
          <input type="text" id="ms-code" class="input mono" placeholder="e.g., 2SYA" value="${esc(
            existingSite ? existingSite.code : ""
          )}" />
        </div>
        <div>
          <label class="field-label">Site Name</label>
          <input type="text" id="ms-name" class="input" placeholder="e.g., Sydney Core DC" value="${esc(
            existingSite ? existingSite.name : ""
          )}" />
        </div>
      </div>
      <div>
        <label class="field-label">Description</label>
        <input type="text" id="ms-desc" class="input" placeholder="Location or facility details" value="${esc(
          existingSite ? existingSite.description : ""
        )}" />
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: existingSite ? "Save Site" : "Create Site",
          className: "btn btn--primary",
          onClick: async () => {
            const code = document.getElementById("ms-code").value.trim().toUpperCase();
            const name = document.getElementById("ms-name").value.trim();
            const description = document.getElementById("ms-desc").value.trim();
            if (!code) {
              showToast("Validation Error", "Site Code is required (e.g., 2SYA)", "error");
              return;
            }
            try {
              appState.snapshot = await apiRequest("/api/v1/sites", "POST", {
                action: "save",
                id: existingSite ? existingSite.id : undefined,
                code,
                name: name || code,
                description,
              });
              closeModal();
              renderAll();
              showToast("Site Saved", `${code} — ${name || code}`, "ok");
            } catch (err) {
              showToast("Error Saving Site", err.message, "error");
            }
          },
        },
      ]
    );
  }

  /* ------------------------------------------------------------------ Teams Screen (/teams) */

  function renderTeamsView(container) {
    const teams = appState.snapshot.teams || [];
    const isAdmin = hasPermission("GLOBAL_ADMIN");

    const rowsHtml = teams
      .map(
        (t) => `
        <tr>
          <td><span class="ws-badge tone-hit mono">${esc(t.code)}</span></td>
          <td style="font-weight:600;">${esc(t.name)}</td>
          <td class="text-muted">${esc(t.description)}</td>
          <td>
            <div style="display:flex; flex-wrap:wrap; gap:4px;">
              ${(t.members || [])
                .map((m) => `<span class="ws-badge tone-offline mono">${esc(m)}</span>`)
                .join("")}
            </div>
          </td>
          <td style="text-align:right;">
            ${
              isAdmin
                ? `<button type="button" class="btn btn--sm btn--ghost" data-edit-team="${esc(
                    t.id
                  )}">&#9998; Edit</button>
                   <button type="button" class="btn btn--sm btn--danger" data-delete-team="${esc(
                     t.id
                   )}">&#128465;</button>`
                : ""
            }
          </td>
        </tr>
      `
      )
      .join("");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>Scope, Zones &amp; RBAC</span>
          <span>/</span>
          <span>Teams</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#128101;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">
              Teams Directory
              <span class="ws-badge tone-brand tabular">${teams.length} Teams</span>
            </h1>
            <div class="page-header__caption">
              Define operational teams used to scope Catalog items, Endpoint Lists, and Dashboards.
            </div>
          </div>
          <div class="page-header__actions">
            ${
              isAdmin
                ? `<button type="button" class="btn btn--primary" id="btn-new-team">+ Define Team</button>`
                : `<span class="ws-badge tone-offline">Global Admin required to edit Teams</span>`
            }
          </div>
        </div>
      </header>

      <section class="page-card">
        <div class="page-card__body page-card__body--flush">
          <table class="ws-table">
            <thead>
              <tr>
                <th>Team Code</th>
                <th>Team Name</th>
                <th>Description</th>
                <th>Members</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </section>
    `;

    const newBtn = document.getElementById("btn-new-team");
    if (newBtn) {
      newBtn.addEventListener("click", () => openTeamModal(null));
    }
  }

  function openTeamModal(existingTeam = null) {
    openModal(
      existingTeam ? `Edit Team — ${existingTeam.name}` : "Define New Team",
      `
      <div style="display:grid; grid-template-columns: 1fr 2fr; gap:12px;">
        <div>
          <label class="field-label">Short Code</label>
          <input type="text" id="mt-code" class="input mono" placeholder="e.g., NETOPS" value="${esc(
            existingTeam ? existingTeam.code : ""
          )}" />
        </div>
        <div>
          <label class="field-label">Team Name</label>
          <input type="text" id="mt-name" class="input" placeholder="e.g., Network Operations" value="${esc(
            existingTeam ? existingTeam.name : ""
          )}" />
        </div>
      </div>
      <div>
        <label class="field-label">Description</label>
        <input type="text" id="mt-desc" class="input" placeholder="Core responsibilities" value="${esc(
          existingTeam ? existingTeam.description : ""
        )}" />
      </div>
      <div>
        <label class="field-label">Member Usernames (comma-separated)</label>
        <input type="text" id="mt-members" class="input mono" placeholder="joperator, priya.nair" value="${esc(
          existingTeam ? (existingTeam.members || []).join(", ") : ""
        )}" />
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: existingTeam ? "Save Team" : "Create Team",
          className: "btn btn--primary",
          onClick: async () => {
            const code = document.getElementById("mt-code").value.trim().toUpperCase();
            const name = document.getElementById("mt-name").value.trim();
            const description = document.getElementById("mt-desc").value.trim();
            const members = document
              .getElementById("mt-members")
              .value.split(",")
              .map((s) => s.trim())
              .filter(Boolean);
            if (!name) {
              showToast("Validation Error", "Team Name is required", "error");
              return;
            }
            try {
              appState.snapshot = await apiRequest("/api/v1/teams", "POST", {
                action: "save",
                id: existingTeam ? existingTeam.id : undefined,
                code: code || name.toUpperCase().slice(0, 8),
                name,
                description,
                members,
              });
              closeModal();
              renderAll();
              showToast("Team Saved", `${name} (${code})`, "ok");
            } catch (err) {
              showToast("Error Saving Team", err.message, "error");
            }
          },
        },
      ]
    );
  }

  /* ------------------------------------------------------------------ Zones & IP CIDRs Screen (/zones) */

  function renderZonesView(container) {
    const zones = appState.snapshot.zones || [];
    const sim = appState.snapshot.simulation || {};
    const isAdmin = hasPermission("GLOBAL_ADMIN");

    const rowsHtml = zones
      .map((z) => {
        const isCurrent = sim.resolved_zone && sim.resolved_zone.id === z.id;
        return `
        <tr>
          <td>
            <div style="font-weight:600; display:flex; align-items:center; gap:8px;">
              <span>${esc(z.name)}</span>
              ${isCurrent ? `<span class="ws-badge tone-ok">Active Client Zone</span>` : ""}
            </div>
            <div class="text-muted" style="font-size:12px;">${esc(z.description)}</div>
          </td>
          <td>
            <div style="display:flex; flex-wrap:wrap; gap:6px;">
              ${(z.cidrs || [])
                .map((c) => `<span class="ws-badge tone-brand mono">${esc(c)}</span>`)
                .join("")}
            </div>
          </td>
          <td class="mono tabular">${z.priority}</td>
          <td style="text-align:right; white-space:nowrap;">
            <button type="button" class="btn btn--sm" data-test-zone="${esc(
              z.id
            )}">Simulate Zone</button>
            ${
              isAdmin
                ? `<button type="button" class="btn btn--sm btn--ghost" data-edit-zone="${esc(
                    z.id
                  )}">&#9998; Edit CIDRs</button>
                   <button type="button" class="btn btn--sm btn--danger" data-delete-zone="${esc(
                     z.id
                   )}">&#128465;</button>`
                : ""
            }
          </td>
        </tr>
      `;
      })
      .join("");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>Scope, Zones &amp; RBAC</span>
          <span>/</span>
          <span>Zones &amp; IP CIDRs</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#127760;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">
              Security Zones &amp; IP CIDRs
              <span class="ws-badge tone-brand tabular">${zones.length} Zones</span>
            </h1>
            <div class="page-header__caption">
              Define Security Zones (e.g., DMZ, Core Network, DC Management) and link them to IPv4/IPv6 CIDR blocks. Longest-prefix match resolves any IP to its Zone.
            </div>
          </div>
          <div class="page-header__actions">
            ${
              isAdmin
                ? `<button type="button" class="btn btn--primary" id="btn-new-zone">+ Define Zone &amp; CIDRs</button>`
                : ""
            }
          </div>
        </div>
      </header>

      <section class="page-card" style="margin-bottom:16px;">
        <header class="page-card__head">
          <div class="page-card__titles">
            <h3 class="page-card__title">IP-to-Zone Longest-Prefix Lookup Tester</h3>
            <div class="page-card__caption">Test any IPv4 or IPv6 address against the defined Zone CIDR table</div>
          </div>
        </header>
        <div class="page-card__body">
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <input type="text" id="zone-lookup-ip" class="input mono" style="max-width:320px;" value="${esc(
              sim.simulated_ip || "10.20.100.15"
            )}" placeholder="Enter IPv4 or IPv6 address..." />
            <button type="button" class="btn btn--primary" id="btn-zone-lookup">Test IP Lookup</button>
            <div id="zone-lookup-result" style="font-size:13px;"></div>
          </div>
        </div>
      </section>

      <section class="page-card">
        <div class="page-card__body page-card__body--flush">
          <table class="ws-table">
            <thead>
              <tr>
                <th>Zone Name &amp; Description</th>
                <th>Linked IPv4 / IPv6 CIDRs</th>
                <th>Priority</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </section>
    `;

    const newZoneBtn = document.getElementById("btn-new-zone");
    if (newZoneBtn) {
      newZoneBtn.addEventListener("click", () => openZoneModal(null));
    }

    const lookupBtn = document.getElementById("btn-zone-lookup");
    if (lookupBtn) {
      lookupBtn.addEventListener("click", async () => {
        const ip = document.getElementById("zone-lookup-ip").value.trim();
        const resEl = document.getElementById("zone-lookup-result");
        try {
          const out = await apiRequest("/api/v1/zones", "POST", { action: "test_ip", ip });
          const win = out.resolution && out.resolution.winning_zone;
          if (win) {
            resEl.innerHTML = `<span class="ws-badge tone-ok">&#10003; Matched Zone: ${esc(
              win.name
            )} (${esc(out.resolution.matched_cidr)}) — ${out.reachable_count} reachable items</span>`;
          } else {
            resEl.innerHTML = `<span class="ws-badge tone-degraded">Unclassified IP (No matching CIDR)</span>`;
          }
        } catch (err) {
          resEl.innerHTML = `<span class="ws-badge tone-blocked">${esc(err.message)}</span>`;
        }
      });
    }

    container.querySelectorAll("[data-test-zone]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await updateSimulation({ override_zone_id: btn.getAttribute("data-test-zone") });
      });
    });
  }

  function openZoneModal(existingZone = null) {
    openModal(
      existingZone ? `Edit Zone — ${existingZone.name}` : "Define Security Zone & IP CIDRs",
      `
      <div style="display:grid; grid-template-columns: 2fr 1fr; gap:12px;">
        <div>
          <label class="field-label">Zone Name (e.g., DMZ)</label>
          <input type="text" id="mz-name" class="input" placeholder="e.g., DMZ" value="${esc(
            existingZone ? existingZone.name : ""
          )}" />
        </div>
        <div>
          <label class="field-label">Priority</label>
          <input type="number" id="mz-priority" class="input mono" value="${esc(
            existingZone ? existingZone.priority : 100
          )}" />
        </div>
      </div>
      <div>
        <label class="field-label">Description</label>
        <input type="text" id="mz-desc" class="input" placeholder="Perimeter &amp; DMZ segment" value="${esc(
          existingZone ? existingZone.description : ""
        )}" />
      </div>
      <div>
        <label class="field-label">Linked IPv4 / IPv6 CIDRs (comma or newline separated)</label>
        <textarea id="mz-cidrs" class="textarea mono" rows="4" placeholder="10.20.100.0/24&#10;192.0.2.0/24">${esc(
          existingZone ? (existingZone.cidrs || []).join("\n") : ""
        )}</textarea>
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: existingZone ? "Save Zone" : "Create Zone",
          className: "btn btn--primary",
          onClick: async () => {
            const name = document.getElementById("mz-name").value.trim();
            const priority = Number(document.getElementById("mz-priority").value) || 100;
            const description = document.getElementById("mz-desc").value.trim();
            const cidrs = document
              .getElementById("mz-cidrs")
              .value.split(/[\n,]+/)
              .map((s) => s.trim())
              .filter(Boolean);
            if (!name || cidrs.length === 0) {
              showToast("Validation Error", "Zone Name and at least 1 CIDR are required", "error");
              return;
            }
            try {
              appState.snapshot = await apiRequest("/api/v1/zones", "POST", {
                action: "save_zone",
                id: existingZone ? existingZone.id : undefined,
                name,
                description,
                cidrs,
                priority,
              });
              closeModal();
              renderAll();
              showToast("Zone Saved", `${name} (${cidrs.join(", ")})`, "ok");
            } catch (err) {
              showToast("Zone Error", err.message, "error");
            }
          },
        },
      ]
    );
  }

  /* ------------------------------------------------------------------ RBAC Screen (/rbac) */

  function renderRbacView(container) {
    const users = appState.snapshot.users || [];
    const currentUser = getCurrentUser();
    const isAdmin = hasPermission("GLOBAL_ADMIN");
    const teamMap = getTeamMap();

    const rowsHtml = users
      .map((u) => {
        const isCurrent = u.id === currentUser.id;
        const perms = new Set(u.permissions || []);
        const userTeams = (u.team_ids || [])
          .map((tid) => (teamMap[tid] ? teamMap[tid].code : tid))
          .join(", ");

        return `
        <tr>
          <td>
            <div style="font-weight:600; display:flex; align-items:center; gap:8px;">
              <span>${esc(u.display_name)}</span>
              ${isCurrent ? `<span class="ws-badge tone-ok">Active Session</span>` : ""}
            </div>
            <div class="mono text-muted" style="font-size:12px;">${esc(u.username)}</div>
          </td>
          <td>
            ${
              userTeams
                ? `<span class="ws-badge tone-hit mono">${esc(userTeams)}</span>`
                : `<span class="text-muted">None</span>`
            }
          </td>
          <td>
            <span class="ws-badge ${
              perms.has("GLOBAL_ADMIN") ? "tone-ok" : "tone-offline"
            }">${perms.has("GLOBAL_ADMIN") ? "✓ Granted" : "—"}</span>
          </td>
          <td>
            <span class="ws-badge ${
              perms.has("CAN_ADD_GLOBAL") || perms.has("GLOBAL_ADMIN")
                ? "tone-ok"
                : "tone-offline"
            }">${
          perms.has("CAN_ADD_GLOBAL") || perms.has("GLOBAL_ADMIN") ? "✓ Granted" : "—"
        }</span>
          </td>
          <td>
            <span class="ws-badge ${
              perms.has("CAN_ADD_TEAM") || perms.has("GLOBAL_ADMIN")
                ? "tone-ok"
                : "tone-offline"
            }">${
          perms.has("CAN_ADD_TEAM") || perms.has("GLOBAL_ADMIN") ? "✓ Granted" : "—"
        }</span>
          </td>
          <td style="text-align:right; white-space:nowrap;">
            ${
              canUseViewAs() && u.id !== getAuthUser().id
                ? `<button type="button" class="btn btn--sm btn--primary" data-view-as-user="${esc(
                    u.id
                  )}" title="View dashboards, navigation, catalog, and lists from ${esc(
                    u.username
                  )}'s perspective">&#128065; View As</button>`
                : ""
            }
            ${
              !isCurrent
                ? `<button type="button" class="btn btn--sm" data-switch-user="${esc(
                    u.id
                  )}">Switch Session</button>`
                : ""
            }
            ${
              isAdmin
                ? `<button type="button" class="btn btn--sm btn--ghost" data-edit-rbac="${esc(
                    u.id
                  )}">&#9998; Edit Permissions</button>`
                : ""
            }
          </td>
        </tr>
      `;
      })
      .join("");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>Scope, Zones &amp; RBAC</span>
          <span>/</span>
          <span>RBAC Permissions</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#128272;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">
              In-App Role-Based Access Control (RBAC)
            </h1>
            <div class="page-header__caption">
              Permissions are defined within the application: <strong>Global Admin</strong>, <strong>Can Add to Global Scope Items</strong>, and <strong>Can Add Team Scope Items</strong>. All users can create Personal scope items, lists, and dashboards.
            </div>
          </div>
          <div class="page-header__actions">
            ${
              isAdmin
                ? `<button type="button" class="btn btn--primary" id="btn-new-rbac-user">+ Add User Account</button>`
                : ""
            }
          </div>
        </div>
      </header>

      <section class="page-card">
        <div class="page-card__body page-card__body--flush" style="overflow-x:auto;">
          <table class="ws-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Teams</th>
                <th>Global Admin</th>
                <th>Can Add to Global Scope Items</th>
                <th>Can Add Team Scope Items</th>
                <th style="text-align:right;">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${rowsHtml}
            </tbody>
          </table>
        </div>
      </section>
    `;

    container.querySelectorAll("[data-view-as-user]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await updateViewAs(btn.getAttribute("data-view-as-user"));
      });
    });

    container.querySelectorAll("[data-switch-user]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await updateSimulation({ active_user_id: btn.getAttribute("data-switch-user") });
      });
    });

    container.querySelectorAll("[data-edit-rbac]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const uid = btn.getAttribute("data-edit-rbac");
        const targetUser = users.find((u) => u.id === uid);
        if (targetUser) openRbacUserModal(targetUser);
      });
    });

    const newUserBtn = document.getElementById("btn-new-rbac-user");
    if (newUserBtn) {
      newUserBtn.addEventListener("click", () => openRbacUserModal(null));
    }
  }

  function openRbacUserModal(existingUser = null) {
    const teams = appState.snapshot.teams || [];
    const selectedPerms = new Set(existingUser ? existingUser.permissions || [] : []);
    const selectedTeams = new Set(existingUser ? existingUser.team_ids || [] : []);

    openModal(
      existingUser ? `Edit RBAC — ${existingUser.username}` : "Add User Account & RBAC Permissions",
      `
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
        <div>
          <label class="field-label">Username</label>
          <input type="text" id="mr-username" class="input mono" ${
            existingUser ? "readonly" : ""
          } value="${esc(existingUser ? existingUser.username : "")}" placeholder="e.g., secops.eng" />
        </div>
        <div>
          <label class="field-label">Display Name</label>
          <input type="text" id="mr-display" class="input" value="${esc(
            existingUser ? existingUser.display_name : ""
          )}" placeholder="e.g., Taylor Kim" />
        </div>
      </div>

      <div>
        <label class="field-label">In-App RBAC Permissions</label>
        <div class="chip-select-grid" style="flex-direction:column; align-items:stretch;">
          <label class="chip-option">
            <input type="checkbox" name="mr-perm-cb" value="GLOBAL_ADMIN" ${
              selectedPerms.has("GLOBAL_ADMIN") ? "checked" : ""
            } />
            <strong>Global Admin</strong>
            <span class="text-muted">— Full administrative access to Teams, Zones, RBAC, and all scopes</span>
          </label>
          <label class="chip-option">
            <input type="checkbox" name="mr-perm-cb" value="CAN_ADD_GLOBAL" ${
              selectedPerms.has("CAN_ADD_GLOBAL") ? "checked" : ""
            } />
            <strong>Can Add to Global Scope Items</strong>
            <span class="text-muted">— Can create and edit Global Catalog items, Global Lists, and Global Dashboards</span>
          </label>
          <label class="chip-option">
            <input type="checkbox" name="mr-perm-cb" value="CAN_ADD_TEAM" ${
              selectedPerms.has("CAN_ADD_TEAM") ? "checked" : ""
            } />
            <strong>Can Add Team Scope Items</strong>
            <span class="text-muted">— Can create and edit Team-scoped Catalog items, Lists, and Dashboards</span>
          </label>
        </div>
      </div>

      <div>
        <label class="field-label">Team Memberships</label>
        <div class="chip-select-grid">
          ${teams
            .map(
              (t) => `
            <label class="chip-option">
              <input type="checkbox" name="mr-team-cb" value="${esc(t.id)}" ${
                selectedTeams.has(t.id) ? "checked" : ""
              } />
              <span class="mono" style="font-weight:600;">${esc(t.code)}</span>
              <span class="text-muted">${esc(t.name)}</span>
            </label>
          `
            )
            .join("")}
        </div>
      </div>
      `,
      [
        { label: "Cancel", className: "btn btn--ghost", onClick: closeModal },
        {
          label: "Save RBAC Permissions",
          className: "btn btn--primary",
          onClick: async () => {
            const username = document.getElementById("mr-username").value.trim();
            const display_name = document.getElementById("mr-display").value.trim() || username;
            const permissions = Array.from(
              document.querySelectorAll("input[name='mr-perm-cb']:checked")
            ).map((el) => el.value);
            const team_ids = Array.from(
              document.querySelectorAll("input[name='mr-team-cb']:checked")
            ).map((el) => el.value);
            if (!username) {
              showToast("Validation Error", "Username is required", "error");
              return;
            }
            try {
              appState.snapshot = await apiRequest("/api/v1/rbac", "POST", {
                action: existingUser ? "update_user" : "create_user",
                user_id: existingUser ? existingUser.id : undefined,
                username,
                display_name,
                permissions,
                team_ids,
              });
              closeModal();
              renderAll();
              showToast("RBAC Permissions Updated", `${username} permissions saved`, "ok");
            } catch (err) {
              showToast("RBAC Update Failed", err.message, "error");
            }
          },
        },
      ]
    );
  }

  /* ------------------------------------------------------------------ System Settings, Profile & Audit Views */

  function renderSettingsView(container) {
    const user = getCurrentUser();
    const isAdmin = hasPermission("GLOBAL_ADMIN");
    const sysSettings = getSystemSettings();
    const accessibleDashboards = getAccessibleDashboards();
    const globalDashboards = accessibleDashboards.filter((d) => d.scope === "GLOBAL");
    const currentGlobalDash = globalDashboards.find(
      (d) => d.id === sysSettings.default_global_dashboard_id
    );
    const effectiveDefaultId = getEffectiveDefaultDashboardId();
    const effectiveDefaultDash = accessibleDashboards.find(
      (d) => d.id === effectiveDefaultId
    );
    const effectiveSource =
      user.effective_default_dashboard_source ||
      (user.default_dashboard_id ? "USER" : "SYSTEM_GLOBAL");

    const globalDashOptions = globalDashboards
      .map(
        (d) =>
          `<option value="${esc(d.id)}" ${
            d.id === sysSettings.default_global_dashboard_id ? "selected" : ""
          }>${esc(d.title)} (${esc(d.id)})</option>`
      )
      .join("");

    const userDashOptions = [
      `<option value="" ${!user.default_dashboard_id ? "selected" : ""}>Use App-Wide Default Global Dashboard (${esc(
        currentGlobalDash ? currentGlobalDash.title : sysSettings.default_global_dashboard_id
      )})</option>`,
      ...accessibleDashboards.map(
        (d) =>
          `<option value="${esc(d.id)}" ${
            user.default_dashboard_id === d.id ? "selected" : ""
          }>${esc(d.title)} [${esc(formatScopeLabel(d.scope))}] (${esc(d.id)})</option>`
      ),
    ].join("");

    const routeRows = [
      {
        path: "/dashboard",
        desc: "Default Dashboard Resolver (navigates to user's Default Dashboard or App-Wide Default Global Dashboard)",
        target: `/dashboard/${effectiveDefaultId}`,
      },
      ...accessibleDashboards.map((d) => ({
        path: `/dashboard/${d.id}`,
        desc: `Dashboard View: ${d.title} (${formatScopeLabel(d.scope)})${
          d.is_global_default ? " • Default Global" : ""
        }${d.is_user_default ? " • My Default" : ""}`,
        target: `/dashboard/${d.id}`,
      })),
      {
        path: `/dashboard/${effectiveDefaultId}/edit`,
        desc: `Dashboard Edit Mode (${
          effectiveDefaultDash ? effectiveDefaultDash.title : effectiveDefaultId
        })`,
        target: `/dashboard/${effectiveDefaultId}/edit`,
      },
      { path: "/catalog", desc: "Connection Catalog Management", target: "/catalog" },
      { path: "/lists", desc: "Connection Lists Management", target: "/lists" },
      { path: "/sites", desc: "Sites Directory", target: "/sites" },
      { path: "/teams", desc: "Teams & Group Memberships", target: "/teams" },
      { path: "/zones", desc: "Network Zones & Reachability Matrix", target: "/zones" },
      { path: "/rbac", desc: "Users & RBAC Governance", target: "/rbac" },
      { path: "/settings", desc: "App-Wide System Settings & Default Dashboards", target: "/settings" },
      { path: "/profile", desc: "SSH & User Profile Preferences", target: "/profile" },
      { path: "/audit", desc: "Portal Audit Log", target: "/audit" },
    ]
      .map(
        (r) => `
        <tr>
          <td class="mono"><a href="${esc(r.target)}" data-route-link="${esc(
          r.target
        )}" style="color:var(--accent-primary); text-decoration:none;">${esc(r.path)}</a></td>
          <td>${esc(r.desc)}</td>
        </tr>
      `
      )
      .join("");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>Administration</span>
          <span>/</span>
          <span>System Settings</span>
          <span>/</span>
          <span class="mono" style="font-size:11px; color:var(--text-secondary);">/settings</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#9881;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">System Settings &amp; Default Dashboards</h1>
            <div class="page-header__caption">Configure the App-Wide Default Global Dashboard, your Personal Default Dashboard, and inspect explicit browser URLs</div>
          </div>
        </div>
      </header>

      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap:16px; margin-bottom:16px;">
        <section class="page-card">
          <div class="page-card__body" style="display:flex; flex-direction:column; gap:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
              <div>
                <h2 style="margin:0; font-size:15px;">App-Wide System Setting: Default Global Dashboard</h2>
                <div class="text-muted" style="font-size:12px;">Fallback dashboard loaded at <span class="mono">/dashboard</span> for any user without a personal default override.</div>
              </div>
              <span class="ws-badge tone-brand">GLOBAL SYSTEM SETTING</span>
            </div>
            <div>
              <label class="field-label">Current Default Global Dashboard</label>
              <div class="mono" style="font-size:12px;">
                ${esc(currentGlobalDash ? currentGlobalDash.title : sysSettings.default_global_dashboard_id)}
                <span class="text-muted">(/dashboard/${esc(sysSettings.default_global_dashboard_id)})</span>
              </div>
              <div class="text-muted" style="font-size:11px; margin-top:2px;">
                Last updated by <span class="mono">${esc(sysSettings.updated_by || "system")}</span> at <span class="mono">${esc(sysSettings.updated_at || "seed")}</span>
              </div>
            </div>
            <div>
              <label class="field-label" for="sys-global-default-select">Select Default Global Dashboard (GLOBAL scope required)</label>
              <select id="sys-global-default-select" class="select" ${!isAdmin ? "disabled" : ""}>
                ${globalDashOptions}
              </select>
              ${
                !isAdmin
                  ? `<div class="text-muted" style="font-size:11px; margin-top:4px;">Only Global Admins can modify the App-Wide Default Global Dashboard.</div>`
                  : ""
              }
            </div>
            <div style="display:flex; justify-content:flex-end;">
              <button type="button" class="btn btn--primary" id="btn-save-system-settings" ${
                !isAdmin ? "disabled" : ""
              }>Save Default Global Dashboard</button>
            </div>
          </div>
        </section>

        <section class="page-card">
          <div class="page-card__body" style="display:flex; flex-direction:column; gap:14px;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
              <div>
                <h2 style="margin:0; font-size:15px;">My Personal Default Dashboard (${esc(user.username)})</h2>
                <div class="text-muted" style="font-size:12px;">Choose your preferred starting dashboard from the dashboards available to you.</div>
              </div>
              <span class="ws-badge ${user.default_dashboard_id ? "tone-ok" : "tone-neutral"}">${
      effectiveSource === "USER" ? "PERSONAL OVERRIDE" : "INHERITING GLOBAL DEFAULT"
    }</span>
            </div>
            <div>
              <label class="field-label">Effective Default Dashboard for ${esc(user.display_name)}</label>
              <div class="mono" style="font-size:12px;">
                ${esc(effectiveDefaultDash ? effectiveDefaultDash.title : effectiveDefaultId)}
                <span class="text-muted">(/dashboard/${esc(effectiveDefaultId)})</span>
              </div>
            </div>
            <div>
              <label class="field-label" for="sys-user-default-select">My Default Dashboard Selection</label>
              <select id="sys-user-default-select" class="select">
                ${userDashOptions}
              </select>
            </div>
            <div style="display:flex; justify-content:flex-end; gap:8px;">
              ${
                user.default_dashboard_id
                  ? `<button type="button" class="btn" id="btn-clear-user-default-settings">Reset to Global Default</button>`
                  : ""
              }
              <button type="button" class="btn btn--primary" id="btn-save-user-default-settings">Save My Default Dashboard</button>
            </div>
          </div>
        </section>
      </div>

      <section class="page-card">
        <div class="page-card__body page-card__body--flush" style="overflow-x:auto;">
          <div style="padding:14px 16px; border-bottom:1px solid var(--border-subtle);">
            <h2 style="margin:0; font-size:14px;">Explicit Browser URL Routing Table</h2>
            <div class="text-muted" style="font-size:12px;">Every view and dashboard in PANIC has a clean, bookmarkable URL visible in the browser address bar.</div>
          </div>
          <table class="ws-table">
            <thead>
              <tr>
                <th>Browser URL Path</th>
                <th>Target View / Description</th>
              </tr>
            </thead>
            <tbody>${routeRows}</tbody>
          </table>
        </div>
      </section>
    `;

    const saveSysBtn = document.getElementById("btn-save-system-settings");
    if (saveSysBtn) {
      saveSysBtn.addEventListener("click", async () => {
        const dashId = document.getElementById("sys-global-default-select").value;
        try {
          appState.snapshot = await apiRequest("/api/v1/settings", "POST", {
            default_global_dashboard_id: dashId,
          });
          renderAll();
          showToast("Default Global Dashboard Updated", `/dashboard/${dashId}`, "ok");
        } catch (err) {
          showToast("System Settings Error", err.message, "error");
        }
      });
    }

    const saveUserBtn = document.getElementById("btn-save-user-default-settings");
    if (saveUserBtn) {
      saveUserBtn.addEventListener("click", async () => {
        const dashId = document.getElementById("sys-user-default-select").value;
        try {
          const res = await apiRequest("/api/v1/dashboards", "POST", {
            action: "set_user_default",
            dashboard_id: dashId || "",
          });
          appState.snapshot = res.state || res;
          renderAll();
          showToast(
            dashId ? "Personal Default Dashboard Saved" : "Reverted to Global Default",
            dashId ? `/dashboard/${dashId}` : "Inheriting Default Global Dashboard",
            "ok"
          );
        } catch (err) {
          showToast("Default Dashboard Error", err.message, "error");
        }
      });
    }

    const clearUserBtn = document.getElementById("btn-clear-user-default-settings");
    if (clearUserBtn) {
      clearUserBtn.addEventListener("click", async () => {
        try {
          const res = await apiRequest("/api/v1/dashboards", "POST", {
            action: "set_user_default",
            dashboard_id: "",
          });
          appState.snapshot = res.state || res;
          renderAll();
          showToast("Personal Default Cleared", "Now using Default Global Dashboard", "ok");
        } catch (err) {
          showToast("Error", err.message, "error");
        }
      });
    }

    container.querySelectorAll("[data-route-link]").forEach((link) => {
      link.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
        ev.preventDefault();
        const target = link.getAttribute("data-route-link");
        window.history.pushState({}, "", target);
        applyPathFromBrowserLocation();
        renderAll(false);
      });
    });
  }

  function renderProfileView(container) {
    const user = getCurrentUser();
    const sysSettings = getSystemSettings();
    const accessibleDashboards = getAccessibleDashboards();
    const globalDefaultDash = (appState.snapshot.dashboards || []).find(
      (d) => d.id === sysSettings.default_global_dashboard_id
    );
    const defaultDashOptions = [
      `<option value="" ${!user.default_dashboard_id ? "selected" : ""}>Inherit App-Wide Default Global Dashboard (${esc(
        globalDefaultDash ? globalDefaultDash.title : sysSettings.default_global_dashboard_id
      )})</option>`,
      ...accessibleDashboards.map(
        (d) =>
          `<option value="${esc(d.id)}" ${
            user.default_dashboard_id === d.id ? "selected" : ""
          }>${esc(d.title)} [${esc(formatScopeLabel(d.scope))}] (/dashboard/${esc(d.id)})</option>`
      ),
    ].join("");

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>System</span>
          <span>/</span>
          <span>SSH &amp; User Profile</span>
          <span>/</span>
          <span class="mono" style="font-size:11px; color:var(--text-secondary);">/profile</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#9881;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">SSH Launcher Template &amp; User Preferences</h1>
            <div class="page-header__caption">Customize your personal Default Dashboard, one-click SSH command template, and display preferences</div>
          </div>
        </div>
      </header>

      <section class="page-card">
        <div class="page-card__body" style="display:flex; flex-direction:column; gap:14px;">
          <div>
            <label class="field-label">Active User</label>
            <div class="mono">${esc(user.display_name)} (${esc(user.username)})</div>
          </div>
          <div>
            <label class="field-label" for="prof-default-dash">My Default Dashboard (loaded at <span class="mono">/dashboard</span>)</label>
            <select id="prof-default-dash" class="select">
              ${defaultDashOptions}
            </select>
            <div class="text-muted" style="font-size:11px; margin-top:4px;">
              Effective Default URL: <span class="mono">${esc(
                user.effective_default_dashboard_url || `/dashboard/${getEffectiveDefaultDashboardId()}`
              )}</span>
              (${
                user.default_dashboard_id
                  ? "Personal Default Override"
                  : "Inherited from App-Wide Default Global Dashboard"
              })
            </div>
          </div>
          <div>
            <label class="field-label" for="prof-remote-user">Default Remote SSH Username</label>
            <input type="text" id="prof-remote-user" class="input mono" value="${esc(
              user.default_remote_user || user.username
            )}" />
          </div>
          <div>
            <label class="field-label" for="prof-ssh-tpl">SSH Command Template (Placeholders: {host}, {port}, {user}, {flags})</label>
            <input type="text" id="prof-ssh-tpl" class="input mono" value="${esc(
              user.ssh_template || "ssh {user}@{host} -p {port} {flags}"
            )}" />
          </div>
          <div style="display:flex; justify-content:flex-end;">
            <button type="button" class="btn btn--primary" id="btn-save-profile">Save Profile</button>
          </div>
        </div>
      </section>
    `;

    const saveBtn = document.getElementById("btn-save-profile");
    if (saveBtn) {
      saveBtn.addEventListener("click", async () => {
        try {
          const chosenDefaultDash = document.getElementById("prof-default-dash").value;
          appState.snapshot = await apiRequest("/api/v1/profile", "POST", {
            default_remote_user: document.getElementById("prof-remote-user").value.trim(),
            ssh_template: document.getElementById("prof-ssh-tpl").value.trim(),
            default_dashboard_id: chosenDefaultDash || "",
          });
          renderAll();
          showToast("Profile Saved", "Updated default dashboard and SSH preferences", "ok");
        } catch (err) {
          showToast("Profile Error", err.message, "error");
        }
      });
    }
  }

  const AUDIT_FILTER_KEYS = ["actor", "action", "target_type", "q", "limit"];

  function auditRowsHtml(entries) {
    if (!entries.length) {
      return `<tr><td colspan="5" class="text-muted">No audit entries match the current filters.</td></tr>`;
    }
    return entries
      .map(
        (e) => `
        <tr>
          <td class="mono text-muted">${esc(e.created_at)}</td>
          <td class="mono">${esc(e.actor_username)}</td>
          <td><span class="ws-badge tone-brand">${esc(e.action)}</span></td>
          <td class="mono">${esc(e.target_type)}:${esc(e.target_id)}</td>
          <td>${esc(e.summary)}</td>
        </tr>
      `
      )
      .join("");
  }

  async function applyAuditFilters(form) {
    const params = new URLSearchParams();
    for (const key of AUDIT_FILTER_KEYS) {
      const val = (form.elements[key] && form.elements[key].value.trim()) || "";
      if (val) params.set(key, val);
    }
    const qs = params.toString();
    window.history.replaceState(window.history.state, "", `/audit${qs ? `?${qs}` : ""}`);
    const tbody = document.getElementById("audit-tbody");
    try {
      const data = await apiRequest(`/api/v1/audit${qs ? `?${qs}` : ""}`);
      if (tbody) tbody.innerHTML = auditRowsHtml(data.entries || []);
      const count = document.getElementById("audit-count");
      if (count) count.textContent = `${data.count} entries`;
    } catch (err) {
      showToast("Audit filter failed", err.message, "error");
    }
  }

  function renderAuditView(container) {
    const entries = appState.snapshot.audit_logs || [];
    const current = new URLSearchParams(window.location.search);
    const field = (key, label, placeholder) => `
      <label class="audit-filter">
        <span class="field-label">${label}</span>
        <input class="input" name="${key}" id="audit-filter-${key}" placeholder="${placeholder}" value="${esc(current.get(key) || "")}" />
      </label>`;

    container.innerHTML = `
      <header class="page-header">
        <div class="page-header__crumbs">
          <span>System</span>
          <span>/</span>
          <span>Audit Log</span>
          <span>/</span>
          <span class="mono" style="font-size:11px; color:var(--text-secondary);">/audit</span>
        </div>
        <div class="page-header__row">
          <div class="page-header__icon">&#128220;</div>
          <div class="page-header__titles">
            <h1 class="page-header__title">Portal Audit Log</h1>
            <div class="page-header__caption">Structured audit trail of endpoint launches, catalog changes, and RBAC updates</div>
          </div>
        </div>
      </header>
      <section class="page-card">
        <form class="audit-filters" id="audit-filter-form">
          ${field("actor", "User", "username")}
          ${field("action", "Action", "e.g. auth. or catalog.")}
          ${field("target_type", "Target type", "e.g. dashboard")}
          ${field("q", "Search", "summary or target id")}
          ${field("limit", "Limit", "100")}
          <div class="audit-filters__actions">
            <button type="submit" class="btn btn--primary btn--sm" id="audit-filter-apply">Apply</button>
            <button type="button" class="btn btn--sm" id="audit-filter-clear">Clear</button>
            <span class="text-muted" id="audit-count">${entries.length} entries</span>
          </div>
        </form>
        <div class="page-card__body page-card__body--flush" style="overflow-x:auto;">
          <table class="ws-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>User</th>
                <th>Action</th>
                <th>Target</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody id="audit-tbody">${auditRowsHtml(entries)}</tbody>
          </table>
        </div>
      </section>
    `;

    const form = document.getElementById("audit-filter-form");
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      applyAuditFilters(form);
    });
    document.getElementById("audit-filter-clear").addEventListener("click", () => {
      form.reset();
      for (const key of AUDIT_FILTER_KEYS) form.elements[key].value = "";
      applyAuditFilters(form);
    });
    if (AUDIT_FILTER_KEYS.some((k) => current.get(k))) applyAuditFilters(form);
  }

  /* ------------------------------------------------------------------ Modal & Command Palette */

  function openModal(title, bodyHtml, footerButtons = []) {
    const backdrop = document.getElementById("modal-backdrop");
    const titleEl = document.getElementById("modal-title");
    const bodyEl = document.getElementById("modal-body");
    const footEl = document.getElementById("modal-foot");
    if (!backdrop || !titleEl || !bodyEl || !footEl) return;

    titleEl.textContent = title;
    bodyEl.innerHTML = bodyHtml;
    footEl.innerHTML = "";
    for (const b of footerButtons) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = b.className || "btn";
      btn.textContent = b.label;
      btn.addEventListener("click", b.onClick);
      footEl.appendChild(btn);
    }
    backdrop.hidden = false;
  }

  function closeModal() {
    const backdrop = document.getElementById("modal-backdrop");
    if (backdrop) backdrop.hidden = true;
  }

  function openPalette() {
    appState.paletteOpen = true;
    appState.paletteQuery = "";
    appState.paletteIndex = 0;
    const backdrop = document.getElementById("palette-backdrop");
    const input = document.getElementById("palette-input");
    if (backdrop) backdrop.hidden = false;
    renderPaletteResults();
    if (input) {
      input.value = "";
      input.focus();
    }
  }

  function closePalette() {
    appState.paletteOpen = false;
    const backdrop = document.getElementById("palette-backdrop");
    if (backdrop) backdrop.hidden = true;
  }

  function renderPaletteResults() {
    const listEl = document.getElementById("palette-results");
    if (!listEl) return;
    const q = (appState.paletteQuery || "").trim().toLowerCase();

    const items = [];
    for (const c of appState.snapshot.catalog || []) {
      const hay = `${c.title} ${c.host} ${c.site || ""} ${c.protocol}`.toLowerCase();
      if (!q || hay.includes(q)) {
        items.push({
          kind: "host",
          label: c.title,
          sub: `${formatHostDisplay(c)} • Site ${c.site || "2SYA"} • ${formatScopeLabel(
            c.scope
          )}`,
          badge: c.protocol,
          action: () => triggerLaunch(c.id),
        });
      }
    }
    for (const d of getAccessibleDashboards()) {
      const hay = `${d.title} ${d.id} /dashboard/${d.id}`.toLowerCase();
      if (!q || hay.includes(q)) {
        items.push({
          kind: "dashboard",
          label: `Dashboard: ${d.title}`,
          sub: `/dashboard/${d.id} • ${d.description}`,
          badge: formatScopeLabel(d.scope),
          action: () => {
            appState.currentView = "dashboard";
            appState.activeDashboardId = d.id;
            appState.editMode = false;
            appState.workingDashboard = null;
            renderAll();
          },
        });
      }
    }

    appState.paletteItems = items.slice(0, 20);
    if (appState.paletteItems.length === 0) {
      listEl.innerHTML = `<div class="text-muted" style="padding:14px;">No matching hosts or dashboards.</div>`;
      return;
    }

    listEl.innerHTML = appState.paletteItems
      .map(
        (it, idx) => `
        <div class="palette__item ${
          idx === appState.paletteIndex ? "palette__item--active" : ""
        }" data-palette-idx="${idx}">
          <span class="ws-badge tone-brand">${esc(it.badge)}</span>
          <div style="flex:1; min-width:0;">
            <div style="font-weight:600;">${esc(it.label)}</div>
            <div class="mono text-muted" style="font-size:11px;">${esc(it.sub)}</div>
          </div>
        </div>
      `
      )
      .join("");

    listEl.querySelectorAll("[data-palette-idx]").forEach((row) => {
      row.addEventListener("click", () => {
        const idx = Number(row.getAttribute("data-palette-idx"));
        const chosen = appState.paletteItems[idx];
        closePalette();
        if (chosen) chosen.action();
      });
    });
  }

  /* ------------------------------------------------------------------ Global Event Delegation & Main Render */

  function renderMainView() {
    const container = document.getElementById("main-view-container");
    if (!container) return;

    switch (appState.currentView) {
      case "lists":
        renderListsView(container);
        break;
      case "catalog":
        renderCatalogView(container);
        break;
      case "sites":
        renderSitesView(container);
        break;
      case "teams":
        renderTeamsView(container);
        break;
      case "zones":
        renderZonesView(container);
        break;
      case "rbac":
        renderRbacView(container);
        break;
      case "settings":
        renderSettingsView(container);
        break;
      case "profile":
        renderProfileView(container);
        break;
      case "audit":
        renderAuditView(container);
        break;
      case "dashboard":
      default:
        renderDashboardView(container);
        break;
    }
  }

  function renderAll(syncUrl = true, replaceHistory = false) {
    if (syncUrl) {
      syncBrowserUrl(replaceHistory);
    }
    renderTopBarSummary();
    renderSimulatorPopover();
    renderRail();
    renderMainView();
  }

  function bindGlobalEvents() {
    window.addEventListener("popstate", () => {
      applyPathFromBrowserLocation();
      renderAll(false);
    });

    document.addEventListener("click", async (ev) => {
      const launchBtn = ev.target.closest("[data-launch-item]");
      if (launchBtn) {
        ev.preventDefault();
        await triggerLaunch(launchBtn.getAttribute("data-launch-item"));
        return;
      }

      const editListBtn = ev.target.closest("[data-edit-list]");
      if (editListBtn) {
        const listId = editListBtn.getAttribute("data-edit-list");
        const lst = (appState.snapshot.lists || []).find((l) => l.id === listId);
        if (lst) openListModal(lst);
        return;
      }

      const delListBtn = ev.target.closest("[data-delete-list]");
      if (delListBtn) {
        const listId = delListBtn.getAttribute("data-delete-list");
        try {
          appState.snapshot = await apiRequest("/api/v1/lists", "POST", {
            action: "delete",
            id: listId,
          });
          renderAll();
          showToast("List Deleted", listId, "ok");
        } catch (err) {
          showToast("Delete Failed", err.message, "error");
        }
        return;
      }

      const editCatBtn = ev.target.closest("[data-edit-catalog]");
      if (editCatBtn) {
        const itemId = editCatBtn.getAttribute("data-edit-catalog");
        const item = (appState.snapshot.catalog || []).find((c) => c.id === itemId);
        if (item) openCatalogItemModal(item);
        return;
      }

      const delCatBtn = ev.target.closest("[data-delete-catalog]");
      if (delCatBtn) {
        const itemId = delCatBtn.getAttribute("data-delete-catalog");
        try {
          const res = await apiRequest("/api/v1/catalog", "POST", {
            action: "delete",
            id: itemId,
          });
          appState.snapshot = res.state;
          renderAll();
          showToast("Catalog Item Deleted", itemId, "ok");
        } catch (err) {
          showToast("Delete Failed", err.message, "error");
        }
        return;
      }

      const editSiteBtn = ev.target.closest("[data-edit-site]");
      if (editSiteBtn) {
        const sid = editSiteBtn.getAttribute("data-edit-site");
        const site = (appState.snapshot.sites || []).find((s) => s.id === sid);
        if (site) openSiteModal(site);
        return;
      }

      const delSiteBtn = ev.target.closest("[data-delete-site]");
      if (delSiteBtn) {
        const sid = delSiteBtn.getAttribute("data-delete-site");
        try {
          appState.snapshot = await apiRequest("/api/v1/sites", "POST", {
            action: "delete",
            id: sid,
          });
          renderAll();
          showToast("Site Deleted", sid, "ok");
        } catch (err) {
          showToast("Delete Failed", err.message, "error");
        }
        return;
      }

      const editTeamBtn = ev.target.closest("[data-edit-team]");
      if (editTeamBtn) {
        const tid = editTeamBtn.getAttribute("data-edit-team");
        const team = (appState.snapshot.teams || []).find((t) => t.id === tid);
        if (team) openTeamModal(team);
        return;
      }

      const delTeamBtn = ev.target.closest("[data-delete-team]");
      if (delTeamBtn) {
        const tid = delTeamBtn.getAttribute("data-delete-team");
        try {
          appState.snapshot = await apiRequest("/api/v1/teams", "POST", {
            action: "delete",
            id: tid,
          });
          renderAll();
          showToast("Team Deleted", tid, "ok");
        } catch (err) {
          showToast("Delete Failed", err.message, "error");
        }
        return;
      }

      const editZoneBtn = ev.target.closest("[data-edit-zone]");
      if (editZoneBtn) {
        const zid = editZoneBtn.getAttribute("data-edit-zone");
        const zone = (appState.snapshot.zones || []).find((z) => z.id === zid);
        if (zone) openZoneModal(zone);
        return;
      }

      const delZoneBtn = ev.target.closest("[data-delete-zone]");
      if (delZoneBtn) {
        const zid = delZoneBtn.getAttribute("data-delete-zone");
        try {
          appState.snapshot = await apiRequest("/api/v1/zones", "POST", {
            action: "delete_zone",
            id: zid,
          });
          renderAll();
          showToast("Zone Deleted", zid, "ok");
        } catch (err) {
          showToast("Delete Failed", err.message, "error");
        }
        return;
      }
    });

    const toggleRailBtn = document.getElementById("btn-toggle-rail");
    if (toggleRailBtn) {
      toggleRailBtn.addEventListener("click", () => {
        appState.railCollapsed = !appState.railCollapsed;
        renderRail();
      });
    }

    const brandHome = document.getElementById("brand-home-link");
    if (brandHome) {
      brandHome.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
        ev.preventDefault();
        appState.currentView = "dashboard";
        appState.activeDashboardId = getEffectiveDefaultDashboardId();
        appState.dashboardEditMode = false;
        renderAll();
      });
    }

    const simToggle = document.getElementById("btn-sim-toggle");
    if (simToggle) {
      simToggle.addEventListener("click", () => {
        appState.simOpen = !appState.simOpen;
        renderSimulatorPopover();
      });
    }

    const simClose = document.getElementById("btn-sim-close");
    if (simClose) {
      simClose.addEventListener("click", () => {
        appState.simOpen = false;
        renderSimulatorPopover();
      });
    }

    const simReset = document.getElementById("btn-sim-reset");
    if (simReset) {
      simReset.addEventListener("click", async () => {
        appState.snapshot = await apiRequest("/api/v1/state", "POST", { action: "reset" });
        appState.activeDashboardId = getEffectiveDefaultDashboardId();
        renderAll();
        showToast("Reset to Seed State", "Restored default fixtures", "ok");
      });
    }

    const densityBtn = document.getElementById("btn-density-toggle");
    if (densityBtn) {
      densityBtn.addEventListener("click", async () => {
        const user = getCurrentUser();
        const next = user.density === "COMPACT" ? "COMFORT" : "COMPACT";
        appState.snapshot = await apiRequest("/api/v1/profile", "POST", { density: next });
        renderAll();
      });
    }

    const themeBtn = document.getElementById("btn-theme-toggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", async () => {
        const user = getCurrentUser();
        const next = user.theme === "DARK" ? "LIGHT" : "DARK";
        appState.snapshot = await apiRequest("/api/v1/profile", "POST", { theme: next });
        renderAll();
      });
    }

    const profileBtn = document.getElementById("btn-profile-nav");
    if (profileBtn) {
      profileBtn.addEventListener("click", (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
        ev.preventDefault();
        appState.currentView = "profile";
        renderAll();
      });
    }

    const openPaletteBtn = document.getElementById("btn-open-palette");
    if (openPaletteBtn) {
      openPaletteBtn.addEventListener("click", () => openPalette());
    }

    const modalCloseBtn = document.getElementById("btn-modal-close");
    if (modalCloseBtn) {
      modalCloseBtn.addEventListener("click", () => closeModal());
    }

    const paletteInput = document.getElementById("palette-input");
    if (paletteInput) {
      paletteInput.addEventListener("input", () => {
        appState.paletteQuery = paletteInput.value;
        appState.paletteIndex = 0;
        renderPaletteResults();
      });
    }

    document.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        if (appState.paletteOpen) closePalette();
        else openPalette();
        return;
      }
      const tag = (ev.target && ev.target.tagName) || "";
      if (
        ev.key === "/" &&
        !appState.paletteOpen &&
        tag !== "INPUT" &&
        tag !== "TEXTAREA" &&
        tag !== "SELECT"
      ) {
        ev.preventDefault();
        openPalette();
        return;
      }
      if (ev.key === "Escape") {
        if (appState.paletteOpen) closePalette();
        closeModal();
        if (appState.simOpen) {
          appState.simOpen = false;
          renderSimulatorPopover();
        }
      }
    });
  }

  applyPathFromBrowserLocation();
  bindGlobalEvents();
  renderAll(true, true);
})();

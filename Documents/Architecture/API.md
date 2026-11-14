# PANIC — API Contract (Stage 6 draft)

> **Status:** Draft for owner review ([ADR-0001](adr/0001-web-server-mongo-split.md)). In Phase B the
> authoritative contract becomes the generated `openapi/server.yaml` (AR-6.3). This page describes
> intent and semantics; field lists are indicative and may gain fields, but must not lose any
> without an ADR.
>
> All paths are served by **panic-server** and reached by the browser through **panic-web** (§9).
> Bodies are JSON (`application/json; charset=utf-8`) unless stated. Timestamps are RFC 3339 UTC.

## 1. Conventions

| Topic | Rule |
|---|---|
| Auth | Session cookie `panic_sessionid` (`HttpOnly`, `SameSite=Lax`, `Secure` in prod). Everything except §4.1 public endpoints requires a session; otherwise `401 UNAUTHENTICATED`. |
| CSRF | Unsafe methods need `X-CSRFToken` = cookie `panic_csrftoken`. `GET /api/v1/auth/csrf` sets/rotates the cookie. On `403 CSRF_FAILED` the client refreshes once and retries once. |
| Request id | Client may send `X-Request-ID` (`^[A-Za-z0-9._:-]{1,128}$`); always echoed. |
| Identity | "Caller" = effective user (the View As subject when active, otherwise the signed-in user). Zone always comes from the real client IP. |
| Ids | Opaque strings; dashboards are UUIDv4. Unknown or **invisible** ids → `404 NOT_FOUND`. |
| Paging (tables) | `?page=1&page_size=50` (max 100). Response envelope: `{"results": [...], "page": 1, "page_size": 50, "total": 4873, "has_next": true}`. |
| Paging (audit) | Keyset: `?limit=100&cursor=<opaque>` → `{"results": [...], "next_cursor": "…" \| null}`. |
| Sorting | `?sort=title` / `?sort=-updated_at`; each endpoint lists its allowed keys (others → `400`). |
| Search | `q` is split on whitespace; every token must prefix-match a `search_keys` token (case-insensitive). Max 8 tokens, 64 chars each. |
| Partial update | `PATCH` with only the fields to change. `PUT` replaces the whole editable representation. |
| Write responses | Return the changed resource only (AR-6.6). Create → `201` + `Location`. Delete → `204`. |

## 2. Versioning, ETag and If-Match

- Every mutable resource has an integer `version` in its body and `ETag: "<version>"` on single-resource reads/writes.
- **Dashboards and endpoint lists:** `PUT`/`PATCH`/`DELETE` **require** `If-Match: "<version>"`.
  Missing → `428 PRECONDITION_REQUIRED`; stale → `409 VERSION_CONFLICT` with
  `{"error_code": "VERSION_CONFLICT", "detail": "...", "current_version": 8}` (the client reloads, shows a
  "changed by someone else" banner, and lets the user re-apply).
- **All other resources:** `If-Match` optional; honoured when present.
- **UI view endpoints** (`/api/v1/ui/...`) return a weak `ETag: W/"<sha256-16 of body>"` and answer
  `If-None-Match` with `304 Not Modified`. The body hash covers zone, View As and preference effects
  automatically.

## 3. Errors

Envelope: `{"error_code": "<ErrorCode>", "detail": "<human text>", "fields": {"<field>": ["msg"]}?, ...extra}`.

| HTTP | `error_code` | When |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Bad input; `fields` lists problems |
| 400 | `CREDENTIAL_HYGIENE_VIOLATION` | AR-2.1 (`hygiene_errors` extra) |
| 400 | `SCOPE_MISMATCH` | List item scope differs from list scope (`errors` extra) |
| 400 | `INVALID_CIDR`, `INVALID_IP_ADDRESS` | Zone CIDRs / test IP |
| 401 | `UNAUTHENTICATED` | No/expired session, bad credentials on login |
| 403 | `PERMISSION_DENIED` | Visible but not allowed (e.g. edit without rights, admin endpoint) |
| 403 | `CSRF_FAILED` | Missing/invalid CSRF token |
| 403 | `VIEW_AS_READ_ONLY` | Mutation while View As is active (pending owner confirmation) |
| 403 | `UNTRUSTED_PEER` | Direct peer not in `PANIC_TRUSTED_PROXY_CIDRS` and policy `reject` |
| 404 | `NOT_FOUND` | Unknown **or invisible** resource; unknown path |
| 409 | `VERSION_CONFLICT` | Stale `If-Match` (`current_version` extra) |
| 409 | `DUPLICATE_CATALOG_ITEM` | Same `normalized_key` in a visible same-scope item; resend with `force_allow_duplicate: true` (`existing_item` summary extra) |
| 409 | `PROTECTED_RESOURCE` | Delete/demote/unpin the app-wide default; delete the last site; remove the last admin; unpin an `always_display` dashboard |
| 413 | `PAYLOAD_TOO_LARGE` | Body > 1 MB, list > `PANIC_LIST_MAX_ITEMS`, dashboard > 100 widgets |
| 428 | `PRECONDITION_REQUIRED` | `If-Match` missing where required |
| 429 | `RATE_LIMITED` | `Retry-After` header set |
| 503 | `DATABASE_UNAVAILABLE` | Mongo unreachable / server selection timeout |

New codes are added to `panic_common.errors.ErrorCode`; codes are never renamed.

## 4. Endpoints

Access: **P** public · **A** any signed-in user · **G** `GLOBAL_ADMIN`. "Proxied" = in panic-web allow-list (§9).

### 4.1 Auth and session

| Method & path | Access | Purpose |
|---|---|---|
| `GET /api/v1/auth/providers` | P | `{instance_name, local_enabled, ldap_enabled, oidc: {enabled, provider_name}}` for the login page |
| `GET /api/v1/auth/csrf` | P | `204`; sets `panic_csrftoken` |
| `POST /api/v1/auth/login` | P (rate-limited per IP and per username) | `{username, password}` → `200 {me}` (local then LDAP); `401 UNAUTHENTICATED` (uniform message, constant-time) |
| `POST /api/v1/auth/logout` | A | `204`; session flushed |
| `GET /auth/oidc/login?next=/dashboard/…` | P | `302` to IdP (PKCE, state, nonce). `next` must be a same-origin path |
| `GET /auth/oidc/callback` | P | `302` to `next` (or `/login?error=…`) |

The `/login` screen is an SPA route; there is no server-rendered HTML. OIDC redirect URI stays
`https://<panic-web host>/auth/oidc/callback` (one per panic-web hostname, all registered at the IdP).

### 4.2 UI views (per-screen reads)

#### `GET /api/v1/ui/bootstrap` — A

Called once per page load (and after sign-in / View As changes).

```json
{
  "instance": {"name": "PANIC", "version": "0.6.0"},
  "me": {"id": "usr-…", "username": "jdoe", "display_name": "J. Doe", "auth_source": "OIDC",
         "prefs": {"density": "COMFORT", "theme": "DARK", "unreachable_policy": "DIM"}},
  "view_as": null,                       // or {"id","username","display_name"} of the subject
  "permissions": {"global_admin": false, "can_add_global": false, "can_add_team": true, "can_view_as": false},
  "client": {"ip": "198.51.100.23", "zone": {"id": "zone-…", "name": "Jump Hosts"}, "zoned": true},
  "nav": {"dashboards": [{"id": "uuid", "title": "Network Ops", "default": true, "locked": true}]},
  "default_dashboard": {"id": "uuid", "source": "USER | SYSTEM_GLOBAL | FALLBACK"}
}
```

`me`/`permissions` describe the effective user; the real admin is in `real_user` (same shape as
`me`) when `view_as` is set. `locked` = cannot be removed from the menu (always_display or app-wide
default). `/` and `/dashboard` route client-side to `default_dashboard.id`.

#### `GET /api/v1/ui/dashboards/{id}` — A (visible dashboards only) · `ETag` / `If-None-Match`

```json
{
  "dashboard": {"id": "uuid", "title": "…", "description": "…", "scope": "TEAM", "team_ids": ["…"],
                "always_display": false, "version": 7, "can_edit": true,
                "is_user_default": false, "is_global_default": false},
  "widgets": [{"id": "w-1", "widget_type": "HOST", "title": "", "grid_x": 1, "grid_y": 1, "grid_w": 4, "grid_h": 1,
               "catalog_item_id": "cat-…"},
              {"id": "w-2", "widget_type": "LIST", "title": "Routers", "grid_x": 5, "grid_y": 1, "grid_w": 8, "grid_h": 2,
               "list_id": "list-…"}],
  "items": {"cat-…": ItemView},
  "lists": {"list-…": {"id": "list-…", "title": "Routers", "scope": "TEAM", "item_count": 240,
                       "item_ids": ["cat-…", "…"], "truncated": true}},
  "unavailable": {"items": ["cat-gone"], "lists": []}
}
```

- Items appear **once** in `items` no matter how many widgets/lists reference them.
- Only items/lists referenced by this dashboard and visible to the caller are included; with
  `unreachable_policy=HIDE` unreachable items are omitted from `items` and from `item_ids`.
- A LIST widget carries at most `PANIC_LIST_WIDGET_MAX_ITEMS` (default 200) ids; `truncated: true`
  tells the UI to show "Show all (240)" linking to `/lists?open=<id>`.
- `unavailable` lists referenced ids that are deleted or invisible (rendered as placeholders).

**`ItemView`** (shared by dashboard, catalog, list and search responses):

```json
{"id": "cat-…", "title": "core-rtr-01", "protocol": "SSH", "target": "rtr01.example.net:22",
 "site": "2SYA", "scope": "TEAM", "zone_names": ["Core"], "tags": ["core"],
 "reachable": true, "unreachable_reason": null,
 "launch": {"kind": "COPY", "command": "ssh jdoe@rtr01.example.net -p 22", "uri": "ssh://jdoe@rtr01.example.net:22"}}
```

`launch.kind`: `OPEN` (`url`, WEB), `COPY` (`command`, SSH/LOCAL_APP, optional `uri`),
`DOWNLOAD` (`href` = `/api/v1/launch/rdp/{id}.rdp`, RDP). Commands are interpolated server-side
with the caller's SSH template and remote user (AR-2.2). Editing fields (`host`, `port`,
`path_or_args`, `account_override`, `custom_uri`, `zone_ids`, `team_ids`, `owner_usernames`,
`description`, `version`, `can_edit`) are **not** in `ItemView`; they come from `GET /api/v1/catalog/{id}`.

#### `GET /api/v1/ui/search?q=rtr&limit=20` — A

`{"results": [{"type": "DASHBOARD|ITEM|LIST", "id": "…", "title": "…", "subtitle": "SSH · 2SYA · Team",
"item": ItemView?}]}` — at most `limit` (≤ 20) visible results across the three types, ranked
title-prefix > token-prefix, then type order. `q` shorter than 2 characters → empty results.
`Enter` in the palette uses `item.launch` directly (no extra round trip).

### 4.3 Dashboards

| Method & path | Access | Notes |
|---|---|---|
| `GET /api/v1/dashboards?scope=&q=&page=` | A | Summaries `{id, title, scope, team_ids, always_display, sort_order, in_menu}` for the "Add existing" and default-dashboard pickers |
| `POST /api/v1/dashboards` | A + scope rights | `{title, description, scope, team_ids?, owner_usernames?, always_display?, set_as_user_default?, set_as_global_default?}` → `201` dashboard resource; pinned to creator's menu. Starts empty (no hard-coded "Routers" widget) |
| `GET /api/v1/dashboards/{id}` | A | Editable resource: properties + `widgets` + `version` (no resolved items) |
| `PATCH /api/v1/dashboards/{id}` | `can_edit` · If-Match | Properties: `title, description, scope, team_ids, owner_usernames, always_display, sort_order` |
| `PUT /api/v1/dashboards/{id}/layout` | `can_edit` · If-Match | `{"widgets": [...]}` full replacement; server clamps grid (`x 1..12`, `w 3..12`, `h 1..6`, `x+w-1 ≤ 12`), checks each referenced item/list is visible, ≤ 100 widgets |
| `DELETE /api/v1/dashboards/{id}` | `can_edit` · If-Match | `409 PROTECTED_RESOURCE` for the app-wide default; removes it from users' pins/defaults (`update_many`) |

### 4.4 Current user ("me")

| Method & path | Access | Notes |
|---|---|---|
| `GET /api/v1/me` | A | Profile: `display_name, default_remote_user, ssh_template, prefs, default_dashboard_id, pinned_dashboard_ids, version` |
| `PATCH /api/v1/me` | A | Any of the above except pins; hygiene rules on `ssh_template` / `default_remote_user` (no spaces, colons, password flags) |
| `PUT /api/v1/me/default-dashboard` | A | `{"dashboard_id": "uuid" \| null}`; must be visible; also pins it |
| `PUT /api/v1/me/menu/{dashboard_id}` | A | Pin (must be visible GLOBAL/TEAM, or own PERSONAL) → `204` |
| `DELETE /api/v1/me/menu/{dashboard_id}` | A | Unpin; `409 PROTECTED_RESOURCE` for `always_display` / app-wide default / last entry |

Writes under `/me` act on the **real** signed-in user and are refused during View As.

### 4.5 Catalog

| Method & path | Access | Notes |
|---|---|---|
| `GET /api/v1/catalog?group=shared\|personal&protocol=&site=&zone_id=&team_id=&q=&sort=title\|-updated_at\|protocol\|site&page=&page_size=` | A | Page of `ItemView` + `{can_edit, version}` per row. `group=shared` = GLOBAL+TEAM card, `personal` = PERSONAL card |
| `GET /api/v1/catalog/{id}` | A | Full editable resource (all fields, `version`, `can_edit`) |
| `POST /api/v1/catalog` | A + scope rights | Create; hygiene `400`; duplicate `409` unless `force_allow_duplicate` |
| `PATCH /api/v1/catalog/{id}` | `can_edit` · If-Match optional | Same validation; recomputes `normalized_key`, `search_keys` |
| `DELETE /api/v1/catalog/{id}` | `can_edit` | `$pull` from lists (bumps their `version`); HOST widgets become placeholders |
| `POST /api/v1/catalog/preview` | A | `{protocol, host, port, path_or_args, account_override, custom_uri, scope}` → `{normalized_key, resolved_host, resolved_port, hygiene_passed, hygiene_errors, duplicate: {id, title}?}` (visible same-scope matches only) |
| `GET /api/v1/launch/rdp/{id}.rdp` | A (visible; reachable when policy is HIDE) | `application/x-rdp`, `Content-Disposition: attachment`, `Cache-Control: no-store`; audited. `?user=` override sanitised |

### 4.6 Endpoint lists

| Method & path | Access | Notes |
|---|---|---|
| `GET /api/v1/lists?group=shared\|personal&q=&sort=&page=` | A | Summaries `{id, title, description, scope, team_ids, item_count, version, can_edit}` (no items) |
| `GET /api/v1/lists/{id}` | A | Resource with ordered `item_ids` and `items: [ItemView]` (≤ `PANIC_LIST_MAX_ITEMS`, default 500), `version`, `can_edit` — used by the Edit List modal and "Show all" |
| `POST /api/v1/lists` | A + scope rights | `{title, description, scope, team_ids?, owner_usernames?, item_ids}` → `201` |
| `PUT /api/v1/lists/{id}` | `can_edit` · **If-Match** | Full replacement incl. **ordered** `item_ids` (the only way to reorder; Edit List modal) |
| `DELETE /api/v1/lists/{id}` | `can_edit` · **If-Match** | LIST widgets become placeholders |

### 4.7 Administration (Global Admin unless noted)

| Method & path | Access | Notes |
|---|---|---|
| `GET /api/v1/sites` | A | All sites `{id, code, name, description}` (small; for pickers) |
| `POST /api/v1/sites` · `PATCH /api/v1/sites/{id}` · `DELETE /api/v1/sites/{id}` | G | Code unique (`400`); rename cascades to items; last site `409 PROTECTED_RESOURCE` |
| `GET /api/v1/teams` | A | `{id, code, name, description}` (pickers) |
| `GET /api/v1/teams/{id}/members?page=` | G | Paged user summaries |
| `POST /api/v1/teams` · `PATCH /api/v1/teams/{id}` · `DELETE /api/v1/teams/{id}` | G | Delete `$pull`s the id from users; resources still referencing it are reported in the response (`{orphaned: {catalog: n, lists: n, dashboards: n}}`) |
| `GET /api/v1/zones` | A | Non-admins: `{id, name}`; admins: `+ description, priority, cidrs, version` |
| `POST /api/v1/zones` · `PATCH /api/v1/zones/{id}` · `DELETE /api/v1/zones/{id}` | G | CIDRs validated/canonicalised; delete `$pull`s from items' `zone_ids` (reported) |
| `POST /api/v1/zones/test-ip` | G | `{"ip": "192.0.2.10"}` → `{resolution: {winning_zone, matched_cidr, candidates[]}, reachable_count, blocked_count}` |
| `GET /api/v1/users?q=&permission=&team_id=&page=` | G | `{id, username, display_name, auth_source, permissions, team_ids, last_login_at, version}` |
| `POST /api/v1/users` | G | Pre-provision `{username, display_name?, permissions, team_ids}` (no password; local sign-in stays bootstrap-admin only) |
| `PATCH /api/v1/users/{id}` | G | `{permissions?, team_ids?}`; removing the last `GLOBAL_ADMIN` → `409 PROTECTED_RESOURCE` |
| `PUT /api/v1/admin/view-as` | G (real user) | `{"user_id": "usr-…"}` → `200 bootstrap` payload for the new perspective; audited |
| `DELETE /api/v1/admin/view-as` | signed-in admin | Exit View As → `200 bootstrap`; audited. Allowed during View As |
| `GET /api/v1/settings` | A | `{default_global_dashboard: {id, title}, version}` |
| `PATCH /api/v1/settings` | G | `{default_global_dashboard_id}` (must be GLOBAL) |
| `GET /api/v1/audit?actor=&action=&target_type=&target_id=&q=&since=&until=&limit=&cursor=` | G | Keyset-paged entries (newest first), `limit` ≤ 200 |
| `GET /api/v1/export?shared_only=` | G | Portable JSON (`schema_version: 2`), audited; attachment |
| `GET /api/v1/admin/client-ip` | G | Trust-chain diagnostics (§6) |

### 4.8 Operations

| Method & path | Access | Notes |
|---|---|---|
| `GET /api/v1/health[?ready=1]` | P | `{"status": "ok"}`; `ready=1` adds Mongo ping → `503 {"status": "error", "mongo": "error"}` |
| `GET /api/v1/version` | P | `{"name": "panic-server", "version": "…", "revision": "…"}` |
| `GET /metrics` | server port only | Prometheus; **not proxied** by panic-web |

## 5. Removed endpoints (Stage 1–4)

`GET/POST /api/v1/state`, `POST /api/v1/simulator`, `POST /api/v1/profile`,
action-multiplexed `POST /api/v1/{dashboards,catalog,lists,sites,teams,zones,rbac}`,
`PUT /api/v1/dashboards/{id}/layout` (old shape), `POST /api/v1/catalog/preview-share`,
`POST /login` / `POST /logout` (HTML forms), all server-rendered UI routes and `/static/`.
The response headers `X-Client-IP` / `X-Security-Zone` are dropped (diagnostics endpoint instead).

## 6. Client-IP diagnostics shape

`GET /api/v1/admin/client-ip`:

```json
{
  "remote_addr": "192.0.2.30",
  "peer_trusted": true,
  "policy": {"trust_proxy_headers": true, "header": "X-Forwarded-For", "untrusted_peer_policy": "reject",
             "trusted_proxy_cidrs": ["192.0.2.10/32", "192.0.2.20/32", "192.0.2.30/32"],
             "max_hops": 16, "max_bytes": 4096},
  "raw": {"x_forwarded_for": "203.0.113.9, 198.51.100.23, 192.0.2.10, 192.0.2.20", "forwarded": null, "x_real_ip": null},
  "hops": [
    {"position": 4, "ip": "192.0.2.30",   "source": "peer",   "trusted": true},
    {"position": 3, "ip": "192.0.2.20",   "source": "header", "trusted": true},
    {"position": 2, "ip": "192.0.2.10",   "source": "header", "trusted": true},
    {"position": 1, "ip": "198.51.100.23","source": "header", "trusted": false, "selected": true}
  ],
  "ignored_left_hops": 1,
  "truncated": false,
  "decision": "FIRST_UNTRUSTED_HOP",
  "client_ip": "198.51.100.23",
  "zone": {"id": "zone-…", "name": "Jump Hosts", "matched_cidr": "198.51.100.0/24"},
  "candidates": [{"zone_id": "…", "zone_name": "…", "matched_cidr": "…", "prefix_len": 24, "priority": 100}]
}
```

`decision` ∈ `HEADERS_DISABLED`, `UNTRUSTED_PEER`, `NO_HEADER`, `FIRST_UNTRUSTED_HOP`,
`ALL_HOPS_TRUSTED`, `MALFORMED_HOP`.

## 7. Rate limits

Mongo-backed fixed windows (AR-4.6), keyed by resolved client IP (and username for login):
`PANIC_RATE_LIMIT_LOGIN` (default `10/60` per IP, `5/60` per username via
`PANIC_RATE_LIMIT_LOGIN_USER`), `PANIC_RATE_LIMIT_API` (`300/60` per IP, unsafe methods only).
Exceeded → `429 RATE_LIMITED` + `Retry-After`. Unzoned/untrusted callers share the peer's bucket.

## 8. Payload budgets (uncompressed JSON, reference dataset)

Reference dataset (`panic_seed --profile loadtest`): 5,000 catalog items, 50 users, 12 teams,
20 zones, 200 lists (10–500 items), 60 dashboards (largest: 30 widgets referencing 12 lists /
≈ 600 distinct items). Enforced by `tests/test_payload_budgets.py` (AR-6.2).

| Response | Budget | Mongo round trips |
|---|---|---|
| `GET /ui/bootstrap` | ≤ 8 KB | ≤ 5 |
| `GET /ui/dashboards/{id}` typical (≤ 12 widgets, ≤ 150 items) | ≤ 64 KB | ≤ 6 |
| `GET /ui/dashboards/{id}` largest (200-item widget cap) | ≤ 256 KB | ≤ 6 |
| `GET /ui/dashboards/{id}` with matching `If-None-Match` | 0 B body (`304`) | ≤ 6 |
| `GET /ui/search` | ≤ 16 KB | ≤ 4 |
| `GET /catalog` page (50 rows) | ≤ 48 KB | ≤ 3 |
| `GET /lists` page (50 rows) | ≤ 16 KB | ≤ 2 |
| `GET /lists/{id}` (500 items) | ≤ 256 KB | ≤ 3 |
| Any mutation response | ≤ 32 KB (dashboard layout ≤ 48 KB) | n/a |

panic-web gzips JSON responses (`gzip_types application/json`); budgets are measured before compression.

## 9. panic-web proxy allow-list (`Application/Web/proxy-paths.json`)

```json
{
  "$comment": "AR-6.4: the ONLY server paths panic-web proxies. Consumed by gen_nginx_conf.py (prod) and dev-proxy.ts (dev). Never list /metrics.",
  "prefixes": ["/api/v1/ui/", "/api/v1/auth/", "/api/v1/me/", "/api/v1/dashboards/", "/api/v1/catalog/",
               "/api/v1/lists/", "/api/v1/sites/", "/api/v1/teams/", "/api/v1/zones/", "/api/v1/users/",
               "/api/v1/admin/", "/api/v1/launch/rdp/", "/auth/oidc/"],
  "exact":    ["/api/v1/me", "/api/v1/dashboards", "/api/v1/catalog", "/api/v1/lists", "/api/v1/sites",
               "/api/v1/teams", "/api/v1/zones", "/api/v1/users", "/api/v1/settings", "/api/v1/audit",
               "/api/v1/export", "/api/v1/health", "/api/v1/version"]
}
```

- Validation (generator and a unit test): paths match `^/(api/v1|auth)/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*/?$`,
  prefixes end in `/`, exact paths do not, no duplicates, `/metrics` never present.
- Anything else under `/api/` or `/auth/` → `404 {"error_code": "NOT_FOUND", "source": "web"}` from nginx.
- Requests with dot segments, encoded `.`/`/`/`\`, or empty segments are refused (`404`) by both nginx
  and the dev proxy.
- Proxied requests carry: `Host` (original), `X-Forwarded-For: $proxy_add_x_forwarded_for`,
  `X-Forwarded-Proto` (from the corporate proxy if `http`/`https`, else `$scheme`), `X-Forwarded-Host`,
  `X-Request-ID` (validated or generated). **No** `X-Real-IP`. Body limit 1 MB, read timeout 30 s.
- panic-web serves itself: `/` + SPA routes (`try_files … /index.html`, `Cache-Control: no-cache`),
  `/assets/` (immutable, 1 year), `/healthz`.

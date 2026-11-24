# PANIC — Data Model Specification

> The MongoDB data model, decided in [ADR-0001](adr/0001-web-server-mongo-split.md). There is no
> relational database and no full-snapshot store.

## 1. Layers

| Layer | Where | Role |
|---|---|---|
| Domain models | `panic_common.models` (Pydantic v2) | The contract used by rules, API serializers and the repository. No I/O. |
| Domain rules | `panic_common.rbac`, `panic_common.visibility`, `zones`, `hygiene`, `launchers`, `proxy` | Pure functions. Visibility rules produce a **filter spec** (§5), never a query. |
| Repository | `panic_server.store` | The **only** package that imports `pymongo` / `bson` (AR-4.1). Maps documents to domain models, translates filter specs to Mongo queries, owns indexes. |
| API | `panic_server.api` (DRF) | Request/response shapes in [`API.md`](API.md); never touches documents directly. |

There is no full-state load. Every repository call is scoped to what one screen needs (AR-6.1).

## 2. Connection

- `PANIC_MONGO_URI` (or `PANIC_MONGO_URI_FILE`): standard `mongodb://` / `mongodb+srv://` URI. Replica
  set name, TLS, `authSource`, read preference and timeouts go **in the URI**. The database is the
  URI path component (default `panic` when the path is empty).
- One `MongoClient` per process, created lazily on first use (never at import time and never before
  Gunicorn forks). Writes use `w=majority`; reads use `primary` unless the URI says otherwise.
- `GET /api/v1/health` runs `ping` (bounded by `serverSelectionTimeoutMS`) and returns `503` when it fails.

## 3. Conventions (all collections)

- **`_id`** is a string: UUIDv4 for every new document (short random suffixes would collide at
  a few thousand items). Imports and the demo fixtures keep the ids they
  carry. Exceptions are the fixed ids `system` (settings) and `zone-default` (Default zone). The
  API exposes `_id` as `id`.
- **Timestamps** are BSON dates (UTC): `created_at`, `updated_at`; the API renders them as RFC 3339.
- **`created_by` / `updated_by`**: usernames (the real signed-in user, never a View As subject).
- **`version`** (`int`, starts at `1`) on every mutable document. Every write is
  `find_one_and_update({_id, version: <expected>}, {..., $inc: {version: 1}})`; no match on an
  existing `_id` is a version conflict (`409 VERSION_CONFLICT`, see [`API.md`](API.md) §3).
  `If-Match` is **required** for dashboards and endpoint lists and honoured when sent for
  everything else.
- **Field names** match `panic_common.models`; optional fields are omitted, not stored as `null`,
  except where `null` is meaningful (`default_dashboard_id`).
- **Size bounds** enforced by the API before writing: ≤ 100 widgets per dashboard, ≤ 500 items per
  endpoint list (`PANIC_LIST_MAX_ITEMS`), ≤ 32 tags per item, ≤ 64 CIDRs per zone.

## 4. Collections

### 4.1 `users`

```json
{
  "_id": "usr-6f1c…", "username": "jdoe", "display_name": "J. Doe",
  "auth_source": "LOCAL | OIDC | LDAP",
  "password_hash": "pbkdf2_sha256$…",            // LOCAL only; never leaves the repository
  "default_remote_user": "jdoe",
  "ssh_template": "ssh {user}@{host} -p {port} {flags}",
  "permissions": ["CAN_ADD_TEAM"],                // set only on the users page; never from the IdP
  "team_ids": ["team-…"],                         // single source of truth for membership, set only on the users page (§4.3)
  "disabled": false,                              // disabled users cannot sign in; users are never deleted
  "pinned_dashboard_ids": ["<uuid>"],
  "default_dashboard_id": "<uuid> | null",
  "prefs": {"density": "COMPACT", "theme": "DARK", "unreachable_policy": "DIM"},  // density is stored but not shown: the UI is always compact
  "last_login_at": ISODate, "created_at": ISODate, "updated_at": ISODate, "version": 3
}
```

Indexes: `{username: 1}` unique · `{team_ids: 1}` · `{permissions: 1}` · `{disabled: 1}` · `{search_keys: 1}` (§4.10).

External identity (OIDC, LDAP) is used for authentication only. A first external sign-in
creates the user with `permissions: []` and `team_ids: []`. Later sign-ins update only
`display_name` and `last_login_at`.
Removing `GLOBAL_ADMIN` from, or disabling, the last enabled admin is refused
(`409 PROTECTED_RESOURCE`). `SUPER_ADMIN` always comes with `GLOBAL_ADMIN`. The bootstrap admin
(`PANIC_BOOTSTRAP_ADMIN_USER`, a `LOCAL` account) is a super admin by identity and is given the flag at
sign-in; it cannot be disabled or lose either flag, and only super admins may edit it. API responses
strip `SUPER_ADMIN` from `permissions` for callers who are not super admins (`panic_server.auth.roles`). Disabling a user, or enabling them again, recomputes `orphaned` on
the `PERSONAL` resources they own (§5.1).

### 4.2 `sites`

`{_id, code, name, description, created_at, updated_at, version}`. `code` is upper case.
Indexes: `{code: 1}` unique. Catalog items reference sites by `code`; renaming a code updates
referencing items with one `update_many`.

### 4.3 `teams`

`{_id, code, name, description, created_at, updated_at, version}`.
Indexes: `{code: 1}` unique.

Teams store no member list. Membership lives only in
`users.team_ids` and is edited only on the user page (`/settings/users/<id>`). A team's members
are `users.find({team_ids: <id>})`, shown read-only on `/teams`. External sign-in never changes
team membership: IdP groups are not mapped to anything.

Deleting a team does three things:
- `$pull`s its id from `users.team_ids` and from resources' `team_ids`.
- Marks `TEAM` resources left with no teams as `orphaned` (§5.1).
- Reports how many resources it orphaned.

### 4.4 `zones` (Security Zones)

`{_id, name, description, priority, cidrs: ["192.0.2.0/24", "2001:db8::/48"], builtin?, created_at, updated_at, version}`.

Resolution (most specific wins): the longest matching prefix; on a tie, the zone with the smallest total
address space in that IP version (a zone that is only `192.0.2.0/24` beats one spanning several
networks); then the higher `priority`; then the name. `priority` matters only for exact ties.
CIDRs are canonicalised by `panic_common.zones.validate_cidr_list`. Indexes: `{name: 1}` unique.

**Default zone.** `{_id: "zone-default", name: "Default", builtin: true, cidrs: []}` is created by
`panic_migrate` (step 1) and always exists. It cannot be deleted, renamed or given CIDRs; only its
`description` can be edited. A request whose client location is unknown is placed in it
([`ARCHITECTURE.md`](ARCHITECTURE.md) §5, AR-5.3). The same applies to an IP that matches no
CIDR. Items list it in `zone_ids` like any other zone. `zone_ids: []` ("All Zones") includes it.
Zones are few (tens) and every zoned request needs all of them, so the repository caches the
zone set per process for `PANIC_ZONE_CACHE_TTL_S` (default 10 s) and invalidates its own cache on
writes. Longest-prefix matching stays in `panic_common.zones`.

### 4.5 `catalog_items`

```json
{
  "_id": "…", "title": "core-rtr-01", "description": "",
  "host": "rtr01.example.net", "site": "2SYA",
  "connections": [
    {"protocol": "SSH", "port": 22, "path_or_args": "", "custom_uri": ""},
    {"protocol": "URL", "port": null, "path_or_args": "/ui", "custom_uri": ""}
  ],
  "account_override": "", "tags": ["core"],
  "normalized_keys": ["ssh://rtr01.example.net:22", "url://rtr01.example.net:443/ui"],
  "scope": "TEAM", "team_ids": ["team-…"], "owner_usernames": [], "zone_ids": ["zone-…"],
  "search_keys": ["core", "rtr", "01", "rtr01", "example", "net", "2sya"],
  "created_by": "jdoe", "created_at": ISODate, "updated_by": "jdoe", "updated_at": ISODate, "version": 1
}
```

`connections` holds one entry per protocol (at least one, each at most once, never both `SSH` and
`RDP`), stored in launch order SSH, RDP, URL, LOCAL_APP; the first is the primary. `normalized_keys`
has one key per connection, in the same order. Items written before 0.2 (single `protocol`, `port`,
`path_or_args`, `custom_uri`, `normalized_key`; `WEB` for URL) are converted by `panic_migrate` step 2;
`CatalogItem` also accepts that shape when reading, so old exports still import.

Indexes:

| Index | Serves |
|---|---|
| `{scope: 1, team_ids: 1, title: 1}` | visibility filter + title sort (TEAM branch) |
| `{scope: 1, owner_usernames: 1, title: 1}` | visibility filter (PERSONAL branch) |
| `{scope: 1, title: 1}` | GLOBAL branch, scope-group paging |
| `{normalized_keys: 1, scope: 1}` | duplicate detection (any shared key) |
| `{search_keys: 1}` | Command Palette / catalog search (prefix match) |
| `{connections.protocol: 1}`, `{site: 1}`, `{zone_ids: 1}` | filters; site rename; zone delete clean-up |

### 4.6 `endpoint_lists`

`{_id, title, description, scope, team_ids, owner_usernames, item_ids: [ordered ids], search_keys, created_by, created_at, updated_by, updated_at, version}`.

- Every item must have the list's scope (`SCOPE_MISMATCH`) and be visible to the editor (no
  adding items you cannot see).
- Order changes only through the Edit List modal (`PUT /api/v1/lists/{id}` with the full ordered
  `item_ids`, `If-Match` required).
- Deleting a catalog item `$pull`s it from every list (`{item_ids: id}` index) and bumps those
  lists' `version`.

Indexes: `{scope: 1, team_ids: 1, title: 1}` · `{scope: 1, owner_usernames: 1, title: 1}` ·
`{scope: 1, title: 1}` · `{item_ids: 1}` · `{search_keys: 1}`.

### 4.7 `dashboards`

```json
{
  "_id": "5b0c…-uuid4", "title": "Network Ops", "description": "",
  "scope": "GLOBAL", "team_ids": [], "owner_usernames": [],
  "always_display": true, "sort_order": 10,
  "widgets": [
    {"id": "w-…", "widget_type": "HOST", "title": "", "grid_x": 1, "grid_y": 1, "grid_w": 4, "grid_h": 1,
     "catalog_item_id": "…"},
    {"id": "w-…", "widget_type": "LIST", "title": "Routers", "grid_x": 5, "grid_y": 1, "grid_w": 8, "grid_h": 2,
     "list_id": "…"}
  ],
  "search_keys": ["network", "ops"],
  "created_by": "jdoe", "created_at": ISODate, "updated_by": "jdoe", "updated_at": ISODate, "version": 7
}
```

Widgets are embedded (always read and written with their dashboard; bounded at 100), so they
carry no `dashboard_id`. Deleted items/lists leave widgets in place; the dashboard view renders
them as "unavailable" placeholders.

Indexes: `{scope: 1, team_ids: 1, sort_order: 1}` · `{scope: 1, owner_usernames: 1, sort_order: 1}` ·
`{scope: 1, always_display: 1, sort_order: 1}` · `{widgets.catalog_item_id: 1}` ·
`{widgets.list_id: 1}` · `{search_keys: 1}`.

**Default dashboard resolution** (three small indexed queries at most):
1. `user.default_dashboard_id` if set and visible → `USER`
2. `system_settings.default_global_dashboard_id` if visible → `SYSTEM_GLOBAL`
3. first visible dashboard by `sort_order` → `FALLBACK`

**Navigation menu:** visible dashboards that are `always_display` (GLOBAL/TEAM),
the global default, the user default, or in `pinned_dashboard_ids`; if the user has no pins, all
visible dashboards. Capped at `PANIC_NAV_MAX_DASHBOARDS` (default 100), projected to `_id`, `title`,
`scope`, `always_display`, `sort_order`.

### 4.8 `system_settings`

Single document `{_id: "system", default_global_dashboard_id, updated_by, updated_at, version}`.
The referenced dashboard must be `GLOBAL` and is protected from deletion, unpinning and scope
demotion (enforced in the service layer, re-checked inside the write filter).

### 4.9 `audit_log`

`{_id: ObjectId, created_at: ISODate, actor_username, view_as_username?, action, target_type, target_id, summary, details, client_ip, zone_id?, request_id}`

- Append-only; written by the service layer after each successful mutation, sign-in, View As
  change, `.rdp` download and export. Each entry records the View As subject, client IP, zone
  and request id alongside the real actor.
- **Retention:** TTL index on `created_at` with `expireAfterSeconds = PANIC_AUDIT_RETENTION_DAYS × 86400`
  (default **365** days; `0` disables expiry). `panic_ensure_indexes` changes the TTL in place with
  `collMod` when the setting changes. Long-term retention belongs in the log pipeline (each audit
  event is also logged as JSON).
- Reads are paged by keyset (`created_at`, `_id`) descending.

Indexes: `{created_at: -1, _id: -1}` · `{actor_username: 1, created_at: -1}` ·
`{action: 1, created_at: -1}` · `{target_type: 1, target_id: 1, created_at: -1}` · TTL as above.

### 4.10 `search_keys`

Catalog items, lists, dashboards and users carry `search_keys`: lower-cased tokens of title, host,
site, tags (and username/display name for users) split on non-alphanumerics, plus the whole
lower-cased host. Computed in `panic_common` (pure) on every write. Searches match each query
token as an anchored prefix (`{search_keys: {$regex: "^tok"}}`), which uses the multikey index.
This avoids a Mongo text index (no prefix matching) and an external search engine.

### 4.11 `sessions` (Django sessions)

`{_id: <session_key>, data: <signed/encoded session>, expire_at: ISODate}`. TTL index on
`expire_at` (`expireAfterSeconds: 0`). Session data holds only `panic_user_id`, `panic_view_as_user_id`,
and the OIDC state, nonce and PKCE verifier (CSRF is cookie-based).

**Continuity across replicas** (AR-4.7): the store reads with `ReadPreference.PRIMARY` and
writes with `w=majority`, overriding the URI. A load balancer can therefore move a user between
panic-web or panic-server instances or containers mid-session without a re-login. Removing a
user's sessions on disable is a `delete_many({"uid": <user id>})`, so documents also carry
`uid`, indexed. See ADR-0001 decision 3 for why this is a small repository-backed
`SessionStore` rather than an ORM backend.

### 4.12 `rate_limits`

`{_id: "<bucket>:<key>:<window_start>", count, expire_at}` incremented with an upserting `$inc`.
Correctness relies on the window start in the key, not on the TTL monitor (which runs only every
60 s); the TTL index on `expire_at` just removes old windows. Buckets: `login:ip`, `login:user`,
`api:ip`.

### 4.13 `schema_meta`

`{_id: "schema", version: <int>, migrated_at}`. Data migrations (rare, e.g. back-filling
`search_keys`) are numbered idempotent functions run by `manage.py panic_migrate`; indexes are
created by `manage.py panic_ensure_indexes`. The container entrypoint runs `panic_ensure_indexes`
on every start and `panic_migrate` when `PANIC_MIGRATE_ON_START=true` (the default); set it to
`false` on all but one replica (or run a one-off job).

## 5. Visibility filter spec

`panic_common.visibility.visibility_spec(user) -> VisibilitySpec` (pure, frozen dataclass):

```python
VisibilitySpec(
    username="jdoe",
    team_ids=("team-a", "team-b"),
    all_teams=False,          # True for GLOBAL_ADMIN (sees every TEAM resource)
)
```

The repository translates it into one `$or` for `catalog_items`, `endpoint_lists` and `dashboards`:

```python
{"$or": [
    {"scope": "GLOBAL"},
    {"scope": "TEAM", "team_ids": {"$in": spec.team_ids}},      # or {"scope": "TEAM"} when all_teams
    {"scope": "PERSONAL", "owner_usernames": spec.username},
]}
```

`panic_common.rbac.is_visible_in_scope` stays the single in-memory definition; a test runs both
against the same generated documents (real Mongo) and requires identical results.

Normal queries also add `{"orphaned": {"$ne": true}}`. Global Admins get a second branch
`{"orphaned": true}` (read-only, §5.1).

### 5.1 Orphaned resources (ADR-0001 decision 10)

- **Definition:**
  - a `TEAM` catalog item, list or dashboard with no `team_ids`, or
  - a `PERSONAL` one whose `owner_usernames` holds no enabled user.
- **Storage:** catalog items, lists and dashboards carry a denormalised `orphaned: bool`, indexed
  `{orphaned: 1, scope: 1}`, so that orphan checks are indexed queries rather than joins. It is
  recomputed by the service layer when:
  - a team is deleted
  - a user is disabled or enabled
  - a resource's scope, teams or owners change
  - `panic_migrate` runs a consistency step
- **Visibility:** orphans are visible only to Global Admins, with an "Orphaned" badge. They are
  read-only for everyone: `can_edit` is always false.
- **Actions** (admin only, audited):
  - **Assign to user** (`POST /api/v1/admin/orphans/{kind}/{id}/assign`): sets `scope=PERSONAL`,
    `owner_usernames=[<enabled user>]`, `team_ids=[]` and `orphaned=false`. A list keeps only the
    items that are that user's `PERSONAL` items; the dropped ids are reported. A dashboard keeps
    its widgets, and those the user cannot see render as placeholders.
  - **Delete** (the normal `DELETE`, with the same cascades as any delete).
- The API never creates orphans directly: create and edit require teams or owners.

## 6. Edit rights

`panic_common.rbac.can_edit(user, resource) -> Decision` (pure). It checks ownership and team
membership as well as the scope permission:

| Scope | May create | May edit / delete |
|---|---|---|
| `GLOBAL` | `CAN_ADD_GLOBAL` | `CAN_ADD_GLOBAL` |
| `TEAM` | `CAN_ADD_TEAM` and member of every chosen team (Global Admin: any team) | `CAN_ADD_TEAM` and member of at least one of the resource's teams, before and after the change (Global Admin: any) |
| `PERSONAL` | everyone (owner = self) | an owner only. **Global Admins cannot edit or delete other users' personal resources.** |
| orphan (§5.1) | n/a | nobody. Global Admins may only assign to a user or delete. |

A resource that is not visible is reported as `404 NOT_FOUND`, never `403`. Visible but not
editable is `403 PERMISSION_DENIED`. A visible orphan is `403 ORPHANED_RESOURCE`.

## 7. Export / import

`manage.py panic_export` / `panic_import` keep the full portable JSON format
(`format: panic-export`, `schema_version: 2`). It is used for backup and for provisioning shared
configuration between environments. Files with `schema_version: 1` (from the first,
never-deployed implementation) are not accepted. Users export with `team_ids`, `permissions` and `disabled`.
Password hashes, sessions, rate limits and the audit log are never exported.

The Super Admin config file (`GET /api/v1/admin/config/export`) is a separate, smaller format:
`format: panic-config`, `schema_version: 1`, with `sites`, `teams`, `zones`, `catalog` and `lists`
(personal included). Each record is its `id` plus the editable fields only (no versions, timestamps,
search or normalized keys, orphan flags). Merge-import rules: SPEC §4.7 and
`panic_server.services.config_transfer`.

## 8. Domain enums

- `Protocol`: `URL`, `SSH`, `RDP`, `LOCAL_APP` (`URL` was `WEB` before 0.2)
- `ScopeType`: `GLOBAL`, `TEAM`, `PERSONAL`
- `PermissionFlag`: `SUPER_ADMIN`, `GLOBAL_ADMIN`, `CAN_ADD_GLOBAL`, `CAN_ADD_TEAM`
- `WidgetType`: `HOST`, `LIST`
- `DensityMode`: `COMFORT`, `COMPACT` · `ThemeMode`: `DARK`, `LIGHT` · `UnreachablePolicy`: `HIDE`, `DIM`

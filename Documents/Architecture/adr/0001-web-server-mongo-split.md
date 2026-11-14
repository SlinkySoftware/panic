# ADR-0001: Split panic-web / panic-server, MongoDB only, scoped API

- **Status:** Accepted (owner, 2026-11-14). Decisions 1–9 come from the owner's brief, and
  decisions 10–12 from the owner's review of Phase A. Points the owner has not answered yet are
  listed under "Owner review" as *assumed*. Phase B may start on them, and they can still be
  overridden.
- **Date:** 2026-11-14
- **Tasks:** Stage 6 (`T-S6-01` … `T-S6-14` in [`TASKS.md`](../../TASKS.md))
- **Supersedes:** Stage 2 "relational persistence" and Stage 1 "server-rendered shell + full JSON
  snapshot" (SPEC §3, §5.1 before Stage 6)

## Context

Stages 1–4 produced a working portal with the wrong shape for production:

- Django + Gunicorn renders `templates/panic/index.html` with the **entire** portal snapshot
  embedded, and the vanilla-JS SPA (`panic.js`, ~4,800 lines) reads `appState.snapshot` everywhere.
- A process-wide `STORE` (`MockPortalStore` → `DatabasePortalStore`) sits behind one lock.
  `PortalStoreMiddleware` loads **all** state on every request and diff-persists afterwards. The
  current user, "View As" and the simulated IP live in that shared object, so requests in one
  worker are serialised and per-request identity is shared mutable state.
- Measured with 3,000 endpoints and 44 users: every page load **and** every mutation returns about
  9.8 MB of JSON and takes about 190 ms of server time. Lists embed full item copies and
  dashboards are sent three times.
- A review for this ADR also found authorization gaps in the current API, which the rewrite must
  close (see "Findings in the current code").

Production has an existing HA MongoDB replica set. Users reach PANIC through a corporate reverse
proxy or load balancer. PANIC must run in several network zones, with the server tier behind an
internal load balancer.

## Decisions

1. **Two deployable units, like reference-app.**
   - **panic-web** is nginx serving the built SPA, with no Python. It proxies an allow-list of
     `/api/v1/...` and `/auth/...` paths to `PANIC_SERVER_URL`. The browser stays same-origin, so
     there is no CORS.
   - **panic-server** is a stateless Django + DRF JSON API. N replicas run behind an internal
     load balancer.
   - Several panic-web instances in different zones point at one server load balancer.
   - Each unit has its own standalone compose file (`compose.standalone.web.yaml`,
     `compose.standalone.server.yaml`) for zoned deployment. An all-in-one `compose.yaml` stays
     for demos.

2. **MongoDB only.**
   - Configured with `PANIC_MONGO_URI` / `PANIC_MONGO_URI_FILE`. Replica set, TLS, `authSource`
     and read preference all go in the URI.
   - Removed: SQLite/PostgreSQL support, the Django ORM domain models (`models.py`, migrations),
     `store_db.py`, `state.py` (`MockPortalStore`, global `STORE` and its lock) and
     `PortalStoreMiddleware`.
   - **No data migration.** PANIC is a new application with no production deployments, so
     there is no upgrade path from Stage 1–4 data. `panic_export` / `panic_import` stay as
     backup and provisioning tools, using the Stage 6 format only.

3. **A pymongo repository layer (`panic_server.store`).**
   - It is the only package allowed to import `pymongo` / `bson`. import-linter enforces this (AR-4.1).
   - It returns `panic_common` models and translates pure visibility specs into Mongo queries.
   - Indexes are defined in code (`store/indexes.py`, named `IndexSpec`s) and applied by the
     idempotent `manage.py panic_ensure_indexes`. Data migrations go through `manage.py panic_migrate`.
   - `PANIC_MIGRATE_ON_START=true` on exactly one replica (or a one-off job) and `false` on the rest.
   - **Sessions** use a small `SessionStore` (subclass of
     `django.contrib.sessions.backends.base.SessionBase`) inside `panic_server.store`, writing to
     a `sessions` collection with a TTL index. Any replica can serve any user.
     - *Alternative:* `django-mongodb-backend` with `sessions.backends.db`, as reference-app does. It
       was not chosen because it is an ORM-on-Mongo backend just for one table. It needs a
       Django `DATABASES` entry and migrations, pins the Django minor version, and would be a
       second Mongo client and connection pool. (Assumed; the owner has not answered yet.)

4. **No full-state loading, ever.**
   - Each API call fetches only what the current screen shows:
     - `GET /api/v1/ui/bootstrap` for identity, permissions, client IP + zone, nav and the default dashboard id.
     - `GET /api/v1/ui/dashboards/{id}` for one dashboard plus only the items and lists it
       references, with reachability for the caller's zone and an `ETag`.
     - Paged, filtered and searched catalog, lists and admin tables.
     - `GET /api/v1/ui/search` for the Command Palette (server side, limit 20).
   - Mutations return only the changed resource.
   - Lists and dashboards use optimistic concurrency: a `version` field plus `If-Match`, with
     `409 VERSION_CONFLICT` on mismatch.
   - Visibility rules stay pure in `panic_common` and produce a filter spec. The repository
     turns that spec into a Mongo query.
   - Tests enforce payload-size budgets ([`API.md`](../API.md) §8).

5. **Frontend rewritten in Vue 3 + Quasar + TypeScript** (`Application/Web`, like reference-app).
   - The typed client is generated from the committed OpenAPI file
     (drf-spectacular → `Documents/Architecture/openapi/server.yaml` → openapi-typescript +
     openapi-fetch). It sends the CSRF header and retries once on CSRF failure.
   - Each view fetches its own data. There is no global client cache of collections.
   - Kept:
     - the reference-ui-aligned look
     - the explicit URLs: `/dashboard/<uuid>`, `/dashboard/<uuid>/edit`, `/catalog`, `/lists`,
       `/sites`, `/teams`, `/zones`, `/rbac` (now redirecting), `/settings`, `/profile`,
       `/audit`, `/login`, plus the new `/settings/users` and `/settings/users/<id>`
       (decision 11)
     - HOST and LIST widgets, the 12-column grid and the Command Palette
   - List item reordering happens **only** in the Edit List modal.

6. **The RBAC / source-IP simulator is removed entirely**, in dev and prod (`SimulationState`,
   `/api/v1/simulator`, `PANIC_AUTH_MODE=simulator`, `PANIC_DEV_SIMULATOR_ENABLED`).
   - Identity always comes from a real sign-in: local bootstrap admin, OIDC or LDAP.
   - The zone always comes from the real client IP.
   - Admin **View As** stays as a real, audited admin feature. It is stored per session and
     changes only the permissions and data perspective, never the zone.
   - **View As is read-only** (owner, 2026-11-14): while it is active every mutation returns
     `403 VIEW_AS_READ_ONLY`, except leaving View As. In Stages 1–4, mutations made during
     View As ran as the impersonated user.

7. **X-Forwarded-For is security-critical.**
   - The chain is: user → corporate reverse proxy/LB → panic-web nginx → internal LB → panic-server.
   - nginx **appends** (`$proxy_add_x_forwarded_for`) and never overwrites. It sets no
     `X-Real-IP` and uses no `realip` module.
   - The server builds the hop list (XFF entries plus the direct peer) and walks it right to
     left. It skips hops inside `PANIC_TRUSTED_PROXY_CIDRS`, which must list every proxy tier,
     and uses the first untrusted hop.
   - It fails closed into the **Default** zone (decision 12). If the client's location is
     unknown, the request gets the Default zone. That covers an untrusted direct peer, a
     malformed chain, a chain where every hop is trusted, and an IP that matches no CIDR.
     `PANIC_UNTRUSTED_PEER_POLICY=reject` optionally refuses untrusted direct peers instead
     (`403 UNTRUSTED_PEER`). The default is `default`.
   - An admin-only diagnostics endpoint (`GET /api/v1/admin/client-ip`) shows the raw headers,
     the hops, each trust decision, the resolved IP and the zone.
   - RFC 7239 `Forwarded` is optional (`PANIC_PROXY_IP_HEADER=Forwarded`).
   - `X-Real-IP` support is dropped because a single-value header cannot describe a multi-tier chain.
   - The full trust model is in [`ARCHITECTURE.md`](../ARCHITECTURE.md) §5.

8. **JIT entitlements are out of scope** (already removed).
   - No Redis/Valkey. Rate-limit counters move to a Mongo `rate_limits` collection, using an
     upserting `$inc` with fixed windows and a TTL.
   - `PANIC_CACHE_URL` and the `redis` extra are removed.

9. **CI** (`.gitea/workflows/ci.yaml`):
   - Python checks run first: ruff, mypy, import-linter and pytest. Web checks follow: ESLint,
     Prettier, vue-tsc and Vitest.
   - Mongo-backed tests run against a real Mongo container, started with `docker run` and a
     network alias as reference-app does, because act_runner `services:` lack health waits.
   - An OpenAPI and generated-types drift check runs.
   - **Two images**, `panic-web` and `panic-server`, are built, smoke-tested together and published.
     - They keep the existing tag scheme: `:main` and `:sha-<short>` on main, and `:X.Y.Z`, `:X.Y`
       and `:latest` on `vX.Y.Z` tags.
     - Publishing uses the org secrets `REGISTRY_USER` / `REGISTRY_TOKEN`.

10. **Orphaned resources are read-only** (owner, 2026-11-14).
    - An orphan is one of:
      - a `TEAM` catalog item, list or dashboard with no `team_ids` (for example, after its
        last team was deleted)
      - a `PERSONAL` one whose `owner_usernames` holds no active user (none set, or every
        owner disabled)
    - Orphans are visible **only to Global Admins**, read-only, with an "Orphaned" badge.
    - Admins can take exactly two actions on an orphan:
      - **Assign to user**: the resource becomes `PERSONAL`, owned by the chosen active user.
        For a list, items that are not that user's `PERSONAL` items are dropped and reported.
        For a dashboard, widgets the user cannot see render as placeholders.
      - **Delete**.
    - Both actions are audited. Nobody can edit an orphan, including admins.
    - An admin screen lists all orphans. Deleting a team reports how many resources it orphaned.

11. **Users management in settings** (owner, 2026-11-14).
    - `/settings/users` lists, searches, creates and disables users.
    - `/settings/users/<id>` edits one user: display name, permission flags, team membership,
      enable/disable, and "View As" for that user.
    - Team membership is set **only** on the user page and stored in `users.team_ids`. The
      Teams screen shows members read-only, with links to the user pages.
    - `/rbac` redirects to `/settings/users`.
    - Users are disabled, never deleted, so that the audit trail stays intact. A disabled user
      cannot sign in.
    - *Assumed (owner to confirm):* the IdP group → team mapping (`PANIC_RBAC_TEAM_GROUP_MAP`,
      `PANIC_RBAC_TEAM_GROUP_PREFIX`) is removed, so sign-in never changes a user's teams.
      IdP group → permission mapping stays. Permissions granted by IdP groups (`idp_permissions`,
      refreshed at each external sign-in and shown locked on the user page) are stored
      separately from manual grants (`permissions`), so manual edits survive sign-in. The
      effective permissions are the union of the two.

12. **Default Security Zone** (owner, 2026-11-14).
    - A built-in zone named **Default** (`_id: "zone-default"`) always exists. It has no CIDRs,
      cannot be deleted, and only its description can be edited.
    - Any client whose location is unknown is placed in it: see decision 7, plus an IP that
      matches no zone CIDR.
    - Catalog items can include Default in their zone restrictions like any other zone. "All
      Zones" items are reachable from Default too.
    - Stages 1–4 called this state "unzoned", which no longer exists.

## Findings in the current code (fixed by design in Stage 6)

| # | Finding | Stage 6 rule |
|---|---|---|
| F1 | `POST /api/v1/rbac` (`update_user`, `create_user`) has **no Global Admin check**: any signed-in user can grant themselves `GLOBAL_ADMIN`. | All `/api/v1/users*` mutations require `GLOBAL_ADMIN`. `tests/test_authz_matrix.py` walks every URL pattern (as reference-app AR-6.3 does). |
| F2 | `GET /api/v1/audit` is readable by every signed-in user. | Audit is Global Admin only. |
| F3 | `GET /api/v1/launch/rdp/<id>.rdp` does not check the item's visibility (IDOR). | `.rdp` requires visibility; with `HIDE` policy also zone reachability. |
| F4 | Catalog/list/dashboard edit and delete check only the *scope* permission, not ownership or team membership. Any user can edit another user's `PERSONAL` items. | `panic_common.rbac.can_edit` ([`DATA_MODEL.md`](../DATA_MODEL.md) §6). Invisible resources return 404. |
| F5 | `POST /api/v1/catalog/preview-share` duplicate detection returns the full matching item even when the caller cannot see it. `zones test_ip` lists every catalog item. | Duplicate checks report only visible matches. `test-ip` is admin only and returns counts. |
| F6 | List saves accept item ids the editor cannot see. | Every item must be visible and same-scope. |

**F1–F3 were hotfixed on `main` on 2026-11-14 at the owner's request** (commit `0d55160`, tests in
`Application/Server/tests/test_authz_hotfix.py`). F4–F6 stay open in the Stage 1–4 code until
Stage 6 replaces it.

## Rejected alternatives

- **Keep the full-snapshot store and optimise it.** This means caching, compressing or diffing
  the snapshot. Payload and CPU still grow with the whole dataset rather than with the screen,
  the global lock serialises requests, and shared per-process identity state is a correctness
  hazard. Rejected.
- **SQL (SQLite/PostgreSQL) with the Django ORM.** Production already runs an HA Mongo replica
  set and no HA PostgreSQL. Two database stacks would double operations, CI and tests. Rejected.
- **ORM-on-Mongo for domain data** (django-mongodb-backend models, or an ODM). It hides the
  query shapes (`$or` visibility filters, multikey prefix search, keyset paging,
  `find_one_and_update` versioning) behind an abstraction that fits them poorly. It adds Django
  version coupling and migration machinery for schemaless documents. Rejected in favour of
  explicit pymongo repositories (reference-app AR-3.2 fallback). It is also rejected for sessions
  (decision 3, assumed).
- **Keep the vanilla-JS SPA** and change only its data access. `panic.js` assumes the full
  snapshot in about 4,800 lines. There are no types, no tests, no generated client, and no
  component model for the grid editor and modals. A rewrite on the reference-app stack costs less and
  lets the two products share patterns. Rejected.
- **Server-rendered HTML with htmx-style partials.** It would keep Python in the edge tier and
  break the panic-web/panic-server split (Decision 1). Rejected.
- **Redis/Valkey for rate limits and sessions.** It adds a new HA dependency for small counters
  that Mongo already handles. Rejected (Decision 8).
- **CORS between a separately hosted SPA and the API.** It needs cross-origin cookies and a
  larger CSRF surface. Same-origin proxying through panic-web avoids both. Rejected.

## Consequences

- `panic.js`, `app.css`, the HTML templates, the simulator, `PANIC_DB_*`, `PANIC_SQLITE_PATH`,
  `PANIC_AUTH_MODE`, `PANIC_DEV_SIMULATOR_ENABLED`, `PANIC_CACHE_URL`, `PANIC_STATIC_ROOT` /
  `PANIC_SERVE_STATIC` and the `postgres` / `redis` extras all go away.
- The dev workflow needs Node (pinned in `.tools/`, like reference-app, with no host packages) and one
  local Mongo container. `./panic start` keeps `http://<host>:8120/` as the UI URL: it runs the
  Quasar dev server on 8120 and Django on 8121, with the same `proxy-paths.json` allow-list.
- Tests need Mongo. `./panic test` uses `PANIC_TEST_MONGO_URI` or starts the single dev Mongo
  container. Each test session uses unique database names, which are dropped afterwards.
- The API contract becomes a reviewed artefact (`openapi/server.yaml`). A breaking change needs
  `/api/v2` alongside v1 after the first release.

## Owner review (2026-11-14)

| # | Question | Outcome |
|---|---|---|
| 1 | Hotfix F1–F3 on current `main`? | **Yes.** Done in `0d55160`. |
| 2 | Visibility of orphaned `TEAM` / `PERSONAL` resources | **Admins only, read-only; only "assign to user" or delete** (decision 10). |
| 3 | Sessions: pymongo `SessionStore`, or `django-mongodb-backend`? | *Assumed:* pymongo `SessionStore` (decision 3). |
| 4 | Is View As read-only? | **Yes** (decision 6). |
| 5 | May admins edit or delete other users' `PERSONAL` resources? | **No.** Admins act only on orphans (decision 10). |
| 6 | Where is team membership managed? | **On the user editing page in settings; a users management page is required** (decision 11). The IdP mapping split is *assumed*. |
| 7 | What happens to unknown client locations? | **They get the built-in Default zone** (decision 12). |
| 8 | Limits: 500 items per list, 100 widgets, 200 rows per LIST widget, 100 nav dashboards | **OK.** |
| 9 | Audit retention default | *Assumed:* 365 days (TTL), with `0` meaning keep forever. |
| 10 | Load-test p95 targets and topology (`T-S6-14`) | *Assumed:* as proposed in [`TASKS.md`](../../TASKS.md). |
| 11 | Existing data to migrate? | **None.** This is a new app with no production deployments, so there are no migrations or v1 import (decision 2). |
| 12 | Transition on `main` (the old UI is removed in `T-S6-04` before the Vue views exist) | *Assumed:* accept a temporary API-only or partial UI on `main`. Tagging the last snapshot-UI commit (`stage4-final`) needs the owner's go-ahead. |

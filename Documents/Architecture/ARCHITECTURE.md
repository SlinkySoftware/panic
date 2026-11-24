# PANIC — Enforced Architecture

> The rules here are **mandatory**. Code that violates them is a bug, even if it works.
> Rules are numbered (`AR-x.y`) so reviews and tests can cite them. A rule changes only through
> an accepted ADR in [`adr/`](adr/), and this file is updated in the same change. The current
> design comes from [ADR-0001](adr/0001-web-server-mongo-split.md).

---

## 1. Components and boundaries

```text
browser ──► corporate reverse proxy / LB ──► panic-web (nginx, zone A) ─┐
browser ──► corporate reverse proxy / LB ──► panic-web (nginx, zone B) ─┼─► internal LB ──► panic-server × N ──► MongoDB replica set
                                                                         ┘                    (Django + DRF)
```

| Component | Path | Runtime | May talk to | Must never |
|---|---|---|---|---|
| **Web** (`panic-web`) | `Application/Web` | nginx serving the built Vue 3 + Quasar SPA (prod); Quasar dev server (dev) | Server, over HTTP(S), on allow-listed paths only | Touch MongoDB, contain Python or business logic, or proxy anything not listed in `proxy-paths.json` |
| **Server** (`panic-server`) | `Application/Server` | Django + DRF JSON API under Gunicorn (`gthread`), N stateless replicas | MongoDB; OIDC / LDAP identity providers | Render HTML pages, serve the SPA, proxy SSH/RDP streams, store user passwords for external accounts or any private keys, keep per-process user state |
| **Common** | `Application/Common` | Python library `panic_common` (Pydantic v2 models, visibility/RBAC rules, normalisation, hygiene, CIDR resolution, client-IP chain parsing, `.rdp` and CLI interpolation) | nothing (pure, no I/O) | Import Django, DRF, pymongo/bson, or any network transport |

- **AR-1.1** `panic_common` is a pure library with no Django, database or network dependencies. Enforced by import-linter (§7).
- **AR-1.2** PANIC is a **control plane and session launcher**, never an HTML5 session proxy.
  Sessions run in native client tools (`ssh`, `putty.exe`, `mstsc.exe`, browser tabs, local SOE binaries).
- **AR-1.3** No client modification is required. Launch actions use standard browser
  navigation (`URL`), clipboard command interpolation (`SSH`, `LOCAL_APP`), optional standard URI
  schemes, or streamed `.rdp` files (`Content-Type: application/x-rdp`).
- **AR-1.4** **Explicit, bookmarkable UI URLs.** The SPA router owns `/`, `/dashboard`,
  `/dashboard/<uuid>`, `/dashboard/<uuid>/edit`, `/catalog`, `/lists`, `/sites`, `/teams`,
  `/zones`, `/settings`, `/settings/users`, `/settings/users/<id>`, `/settings/orphans`,
  `/settings/client-ip`, `/profile`, `/audit` and `/login`. `/rbac` redirects to
  `/settings/users`. panic-web answers every non-API, non-asset path with `index.html`
  (history-mode fallback).
- **AR-1.5** Web contains no Python. The image holds nginx, static files and a config template.
  Its only required runtime variable is `PANIC_SERVER_URL`, which is validated at start:
  scheme, host and port only, with no path, credentials or newlines. The optional
  `PANIC_BASE_PATH` serves PANIC under a URL prefix and must match the server's value.
- **AR-1.6** Every user request goes Browser → Web → Server. The SPA uses only relative
  `/api/v1/...` and `/auth/...` URLs and never knows the server's address.
- **AR-1.7** Web does not use `panic_common`. Its TypeScript types are generated from the
  committed OpenAPI document into `Application/Web/src/api/generated/` and never edited by hand.

## 2. Security, hygiene, RBAC and sanitisation

- **AR-2.1** **No credentials stored in catalog items or cards.**
  `panic_common.hygiene.check_credential_hygiene` rejects any submission with embedded
  credentials (`user:pass@host`) or plaintext password flags (`-pw`, `--password`, `sshpass`).
- **AR-2.2** **Launch parameters are always sanitised.** Every value interpolated into `.rdp`
  files or CLI templates passes through `panic_common.launchers.sanitize_launch_param`.
- **AR-2.3** **`.rdp` files are ephemeral.** They are generated in memory per request and
  streamed with `Cache-Control: no-store`. They are never written to disk.
- **AR-2.4** **Zone reachability.**
  - The caller's Security Zone comes **only** from the real client IP (§5), matched against Zone
    CIDRs by longest prefix, then the zone with the smallest total address space, then highest priority, then name. There is no simulator or override in any
    environment.
  - When the location is unknown (§5) or the IP matches no CIDR, the caller is in the built-in
    **Default** zone (`zone-default`). Every request has exactly one zone. The Default zone
    cannot be deleted or given CIDRs.
- **AR-2.5** **Unified scope and same-scope lists.**
  - Catalog items, endpoint lists and dashboards share `ScopeType`.
  - A list may contain only items of its own scope that the editor can see (`SCOPE_MISMATCH`).
  - Sites, Teams, Zones, Users/RBAC, System Settings, Audit, Export and client-IP diagnostics
    require `GLOBAL_ADMIN`.
- **AR-2.6** **Default dashboard governance.**
  - A user's personal default must be a dashboard visible to them.
  - The app-wide default must be `GLOBAL` and is protected from deletion, unpinning and scope demotion.
- **AR-2.7** **Visibility before permission.**
  - Every read and write is filtered by `panic_common.visibility` (pure filter spec, translated by
    the repository).
  - A resource the caller cannot see is reported as `404 NOT_FOUND`, never `403`.
  - Edits require `panic_common.rbac.can_edit`: the scope permission, plus team membership or
    ownership. Global Admins **cannot** edit other users' `PERSONAL` resources. See
    [`DATA_MODEL.md`](DATA_MODEL.md) §6.
  - **Orphans** are `TEAM` resources with no teams, or `PERSONAL` resources with no active
    owner. They are visible only to Global Admins and are read-only for everyone. The only
    actions are "assign to user" and delete, both admin-only and audited
    ([ADR-0001](adr/0001-web-server-mongo-split.md) decision 10).
- **AR-2.8** **Every endpoint declares its access.** Each DRF view declares one of `public`,
  `authenticated` or `admin` through a shared permission class. `tests/test_authz_matrix.py`
  walks every URL pattern and asserts anonymous, plain-user and admin outcomes.
- **AR-2.9** **View As.**
  - Only `GLOBAL_ADMIN` may start it. It is stored in the server-side session. It can change the
    identity used for visibility and permissions, the zone used for reachability, or both. With
    no user it is the admin's own perspective from the chosen zone
    (`client.zone_source: VIEW_AS`).
  - Start and stop are audited. Every audit entry written while it is active records both users.
  - While it is active, every mutation except leaving View As is refused (`403 VIEW_AS_READ_ONLY`).
- **AR-2.11** **Users and teams.**
  - Users are managed on `/settings/users`. Team membership is set only on the user page
    (`users.team_ids`).
  - Users are disabled, never deleted, and disabled users cannot sign in.
  - **External identity (OIDC, LDAP) is used for authentication only.** Permissions and teams
    are set only on the users pages. IdP groups and claims are never mapped to them, and
    sign-in never changes them.
  - A first external sign-in provisions a user with no permissions and no teams.
  - The last enabled `GLOBAL_ADMIN` cannot have that permission removed and cannot be disabled.
- **AR-2.10** **CSRF and cookies.**
  - Session cookies are `HttpOnly` and `SameSite=Lax`, and `Secure` in prod.
  - Every unsafe method needs `X-CSRFToken`, which matches the `panic_csrftoken` cookie.
    `PANIC_CSRF_TRUSTED_ORIGINS` lists the public origin of **every** panic-web instance.
  - The SPA retries a CSRF failure once after refreshing the token.

## 3. Observability and configuration

- **AR-3.1** Every setting comes from environment variables (`PANIC_*`, or `PANIC_*_FILE` for
  secrets) through `panic_server.conf`, or `PANIC_SERVER_URL` for Web. No real hostnames, IPs,
  usernames or secrets are committed. Fixtures, docs and tests use only `example.com`/`.net`,
  RFC 5737 and RFC 3849 (and RFC 1918 where already used).
- **AR-3.2** Logs are structured JSON on stdout (`ts, level, component, logger, msg, request_id`).
  The SPA sends an `X-Request-ID` with every API call (the dev proxy generates one when it is
  missing), Web forwards it, and Server accepts or generates it, logs it on every line and echoes it.
- **AR-3.3** `GET /api/v1/health` reports liveness. `?ready=1` adds a Mongo `ping` and returns
  `503` if it fails. `/api/v1/version` reports the build. `/metrics` (Prometheus) is served
  by Server on its own port and is **not** proxied by Web. Web answers `GET /healthz` itself.
- **AR-3.4** Error responses use one JSON envelope (`error_code`, `detail`, optional `fields`).
  `error_code` comes from the `panic_common.errors.ErrorCode` enum ([`API.md`](API.md) §3).

## 4. Persistence (MongoDB)

- **AR-4.1** Only `panic_server.store` imports `pymongo` / `bson` or opens a Mongo connection.
  Enforced by import-linter (§7).
- **AR-4.2** No SQL and no Django ORM for domain data. `django.db.models` is not imported anywhere
  in `panic_server` (import-linter). Sessions use a `SessionStore` implemented in
  `panic_server.store`.
- **AR-4.3** Each process has one `MongoClient`, created lazily on first use after Gunicorn forks
  (`preload_app = False`), never at import time. Tests may call `store.client.reset_client()`.
- **AR-4.4** Indexes are defined in code (`panic_server/store/indexes.py`, named `IndexSpec`s) and
  applied by the idempotent `manage.py panic_ensure_indexes`. A same-named index with a different
  definition is an error. Data migrations are numbered, idempotent steps run by
  `manage.py panic_migrate`. The server container runs `panic_ensure_indexes` on every start and
  `panic_migrate` when `PANIC_MIGRATE_ON_START=true` (the default).
- **AR-4.5** Mutable documents carry `version`. Writes are compare-and-set on `version`.
  Dashboards and lists require `If-Match`. A mismatch is `409 VERSION_CONFLICT`, and a missing
  `If-Match` is `428 PRECONDITION_REQUIRED`.
- **AR-4.6** Server is stateless. Sessions, rate-limit counters and audit records live in Mongo,
  with no local disk state and no in-process user state. Any replica can serve any request.
  The zone list may be cached per process for at most `PANIC_ZONE_CACHE_TTL_S`.
- **AR-4.7** **Session continuity.** A load balancer may move a user to any panic-web or
  panic-server instance or container at any time without interrupting the session.
  - There are no sticky sessions.
  - The session store reads from the primary and writes with `w=majority`, whatever read
    preference the URI sets.
  - `PANIC_DJANGO_SECRET_KEY` is identical on every replica.
  - OIDC flow state lives in the session.
  - CSRF is cookie-based.
  - panic-web instances that share users share one public hostname, or set
    `PANIC_SESSION_COOKIE_DOMAIN`.
  - Verified by a cross-replica session test and by the two-replica CI smoke test
    ([ADR-0001](adr/0001-web-server-mongo-split.md) decision 3).

## 5. Client IP and Security Zone trust model

The chain is: **user → corporate reverse proxy/LB → panic-web (nginx) → internal LB → panic-server**.

- **AR-5.1** Every proxy tier **appends** to `X-Forwarded-For` and never replaces it. panic-web uses
  `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`. It does not use the `realip`
  module (`set_real_ip_from` / `real_ip_header`) and does not set `X-Real-IP`. nginx ≥ 1.23 is
  required so that repeated `X-Forwarded-For` headers are joined, not dropped. An L4 internal LB
  must preserve the source address or use PROXY protocol, or be listed as trusted.
- **AR-5.2** `PANIC_TRUSTED_PROXY_CIDRS` must list **every** proxy tier that can be a hop: the
  corporate proxies, the panic-web hosts and containers, and the internal LB. Use tight
  prefixes (ideally `/32` and `/128`), never subnets that also contain jump hosts. A jump host
  inside a trusted range would be skipped as if it were a proxy.
- **AR-5.3** Resolution is in `panic_common.proxy` (pure):
  1. `peer = REMOTE_ADDR`.
  2. If header trust is off (`PANIC_TRUST_PROXY_HEADERS=false`), the client is `peer` and its
     zone is resolved normally.
  3. If `peer` is **not** trusted, the request is an *untrusted peer* and its headers are
     ignored.
     - With `PANIC_UNTRUSTED_PEER_POLICY=default` (the default), the client IP is `peer`, the
       location is unknown, and the zone is **Default**.
     - With `reject`, it gets `403 UNTRUSTED_PEER`, except `health` and `version` from loopback.
  4. Otherwise the hops are the parsed entries of the configured header
     (`PANIC_PROXY_IP_HEADER`: `X-Forwarded-For` by default, or `Forwarded`, never both) followed
     by `peer`. Only the right-most `PANIC_XFF_MAX_HOPS` hops (default 16) are considered,
     and a header longer than `PANIC_XFF_MAX_BYTES` (default 4096) is truncated from the left.
  5. Walk right to left and skip trusted hops. The **first untrusted hop** is the client.
  6. If the walk reaches a token that is not an IP before finding an untrusted hop (`unknown`,
     an obfuscated `Forwarded` identifier, garbage), it stops. The location is unknown, so the
     request gets the **Default** zone, and the client IP is recorded as the last trusted hop. Ports (`192.0.2.1:443`, `[2001:db8::1]:443`) and
     IPv4-mapped IPv6 are normalised. Tokens to the left of the client are never parsed for trust.
  7. If every considered hop is trusted, the location is unknown and the request gets the
     **Default** zone (decision `ALL_HOPS_TRUSTED`).
  8. A resolved client IP that matches no zone CIDR also gets the **Default** zone
     (`zone_source: DEFAULT`). Otherwise `zone_source` is `CIDR`.
- **AR-5.4** The resolution and every hop's trust decision are recorded on the request context.
  `GET /api/v1/admin/client-ip` (admin only) returns them: raw header values, hops, decisions,
  resolved IP, zone and candidate zones. Server also returns the resolved IP and zone id on every
  response in the `X-Client-IP` and `X-Security-Zone` headers.
- **AR-5.5** Tests cover:
  - multi-hop chains through all four tiers
  - spoofed `X-Forwarded-For` from an untrusted peer
  - a client-supplied left-hand prefix
  - IPv6 and bracketed/ported forms
  - junk and `unknown` hops
  - over-long headers and too many hops
  - repeated header lines
  - `Forwarded` parsing
  - the `default` / `reject` policies, and the Default-zone fallback for every unknown-location case
  - the `ALL_HOPS_TRUSTED` case

## 6. API and data access

- **AR-6.1** **No full-state loading.** No endpoint returns, and no request loads, the whole
  portal. Each screen calls a scoped endpoint ([`API.md`](API.md)). Lists are paged (maximum
  page size 100) and searches are limited (maximum 20 for the palette).
- **AR-6.2** **Payload budgets are tested.** `tests/test_payload_budgets.py` seeds the reference
  dataset (5,000 endpoints, 50 users, 200 lists, 60 dashboards). It asserts the uncompressed
  size budgets in [`API.md`](API.md) §8 and the number of Mongo round trips per endpoint
  (command-listener counter).
- **AR-6.3** **The contract is the committed OpenAPI 3.1 document.** drf-spectacular generates
  `Documents/Architecture/openapi/server.yaml` with `--validate --fail-on-warn`. It is never
  edited by hand. `./panic contracts` regenerates it and the TypeScript types, and
  `./panic contracts --check` (in CI) fails on any drift. The version is in the path
  (`/api/v1`). After the first release, a breaking change needs `/api/v2` alongside v1 for one
  release.
- **AR-6.4** **One proxy allow-list.** `Application/Web/proxy-paths.json` is the only list of
  server paths Web forwards. The nginx template generator (`Build/scripts/gen_nginx_conf.py`)
  and the dev proxy both consume it, and a unit test checks they agree. Everything else under
  `/api/` returns `404` from Web. `/metrics` is never listed.
- **AR-6.5** **Layers.** `panic_server.api` (DRF views and serializers) → `panic_server.services`
  (use cases: authorization, invariants, audit) → `panic_server.store` (repositories). Views are
  thin. Services do not import DRF; they raise `panic_server.api.errors.ApiError`, and
  `services.audit` and `services.view_as` take the Django request. The store never imports
  services or api. This rule is checked in review; it is not an import-linter contract.
- **AR-6.6** **Mutations return only the changed resource**, with its new `version` and `ETag`.
  They never return a snapshot. Clients refetch other views as needed.
- **AR-6.7** **Conditional reads.** `GET /api/v1/ui/dashboards/{id}` sends a weak `ETag` (hash of
  the response body) and honours `If-None-Match` with `304`. Resource reads send
  `ETag: "<version>"`.

## 7. import-linter contracts

Configured in `pyproject.toml` (`[tool.importlinter]`, `include_external_packages = true`).

| Contract | Type | Source | Forbidden / rule | Notes |
|---|---|---|---|---|
| **AR-1.1** Common is a pure library | forbidden | `panic_common` | `panic_server`, `django`, `rest_framework`, `pymongo`, `bson`, `httpx`, `ldap3`, `requests`, `socket`, `ssl` | |
| **AR-4.1** Only the repository imports pymongo | forbidden | `panic_server` | `pymongo`, `bson` | `ignore_imports = ["panic_server.store.** -> pymongo", "panic_server.store.** -> bson"]`, `allow_indirect_imports = true` |
| **AR-4.2** No ORM | forbidden | `panic_server` | `django.db.models` | `allow_indirect_imports = true` (direct imports only: Django itself reaches `django.db.models` indirectly) |

## 8. Repository layout

```text
Application/
  Common/panic_common/        models, errors, rbac, visibility, zones, proxy, hygiene, launchers, search_keys
  Server/panic_server/
    settings.py conf.py logging.py middleware.py security.py paths.py gunicorn_conf.py wsgi.py
    context.py                per-request RequestContext (real user, effective user, view-as, client IP, zone)
    auth/                     local, OIDC, LDAP adapters; JSON login/logout; session helpers
    api/                      DRF views, serializers, pagination, etag, exception handler, urls
    services/                 dashboards, catalog, lists, admin, profile, search, audit, launch, export/import
    store/                    client, indexes, sessions, rate_limits, repos/*, filters (ONLY pymongo importer)
    management/commands/      panic_ensure_indexes, panic_migrate, panic_seed, panic_export, panic_import,
                              panic_examples, panic_user_admin
  Web/                        Vue 3 + Quasar + TS SPA; proxy-paths.json; dev-proxy.ts; src/api/generated/
Build/
  Containers/web/ server/ common/   Containerfiles, entrypoints, panic-env.sh (*_FILE handling)
  Containers/compose.yaml compose.standalone.web.yaml compose.standalone.server.yaml compose.dev-mongo.yaml
  scripts/gen_nginx_conf.py   ci/ (mongo_service.sh, contract_checks.sh, container_smoke.sh)   LoadTest/
Documents/Architecture/       ARCHITECTURE.md DATA_MODEL.md API.md adr/ openapi/server.yaml
```

# PANIC Configuration Reference

Every setting comes from the environment (AR-3.1). Any variable may instead be supplied as
`<NAME>_FILE` pointing at a file whose contents are the value (Docker / Kubernetes secrets); the
`_FILE` form wins when both are set. Booleans accept `true/false/1/0/yes/no/on/off`; lists are
comma-separated. Source of truth: the server code (`Application/Server/panic_server/`), both images'
entrypoints and health checks (`Build/Containers/`) and the compose files; a test
(`tests/test_e2e_workflows.py`) fails if any `PANIC_*` variable they read is missing from this page.

All examples use reserved documentation names and addresses (`example.com`, RFC 5737, RFC 3849).

## Core

| Variable | Default | Description |
|---|---|---|
| `PANIC_ENV` | `dev` | `dev`, `test` or `prod`. `prod` enforces a strong secret key and secure cookies. |
| `PANIC_DJANGO_SECRET_KEY` | dev placeholder | Django signing key. **Required in prod** (≥ 32 chars, not the placeholder). Prefer `PANIC_DJANGO_SECRET_KEY_FILE`. |
| `PANIC_DEBUG` | `true` unless prod | Django debug mode. Never enable in production. |
| `PANIC_ALLOWED_HOSTS` | `127.0.0.1,localhost,testserver,*` | Accepted `Host` headers. Set explicitly in prod, e.g. `panic.example.com`. |
| `PANIC_CSRF_TRUSTED_ORIGINS` | *(empty)* | Origins trusted for CSRF behind TLS-terminating proxies, e.g. `https://panic.example.com`. |
| `PANIC_INSTANCE_NAME` | `PANIC` | Name shown in the top bar and login page. |
| `PANIC_BASE_PATH` | *(empty: `/`)* | URL prefix when PANIC shares a host name with other applications, e.g. `/panic` (`panic`, `/panic/` are the same). Letters, digits, `-` and `_` per segment. **Set the same value on panic-server and panic-web.** The server strips it from incoming paths (it still answers without it, for the health check and `/metrics`), puts it on its redirects and `.rdp` links, and scopes the session and CSRF cookies to `<prefix>/`. See DEPLOYMENT.md §2. |
| `PANIC_TZ` | `UTC` | Display time zone. |
| `PANIC_LOG_LEVEL` | `INFO` | Python log level. |
| `PANIC_LOG_FORMAT` | `json` | `json` (structured, with request id) or `console`. |
| `PANIC_SERVER_BIND` | `0.0.0.0:8121` (`./panic`), `0.0.0.0:8210` (container) | Gunicorn / dev server bind address. |

## Container init (panic-server image)

PANIC has no relational database: all domain data, sessions and rate limits live in MongoDB (see
"MongoDB" below and [`DATA_MODEL.md`](../Architecture/DATA_MODEL.md)). On start the entrypoint always
runs `panic_ensure_indexes`, then:

| Variable | Default | Description |
|---|---|---|
| `PANIC_MIGRATE_ON_START` | `true` | Run `panic_migrate` (MongoDB data migrations). Set `false` on all but one replica if you prefer to migrate from a single place, or run `docker run … panic-server init` before a rollout. |
| `PANIC_SEED_ON_START` | `never` in prod, else `if-empty` | `if-empty` seeds the demo fixtures into an empty database; `never` does not. |

## Gunicorn (container)

| Variable | Default | Description |
|---|---|---|
| `PANIC_GUNICORN_WORKERS` | `2` | Worker processes. |
| `PANIC_GUNICORN_THREADS` | `8` | Threads per worker (`gthread`; `preload_app` is off so each worker opens its own MongoClient). |
| `PANIC_GUNICORN_TIMEOUT` | `30` | Worker timeout (s). |
| `PANIC_GUNICORN_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Gunicorn `forwarded_allow_ips` (scheme headers only; client IPs use `PANIC_TRUSTED_PROXY_CIDRS`). |

Settings live in `panic_server/gunicorn_conf.py`; `PANIC_SERVER_BIND` sets the listen address.

## Reverse proxy & Security Zones

| Variable | Default | Description |
|---|---|---|
| `PANIC_TRUST_PROXY_HEADERS` | `true` | Honour the client-IP header **only** from `PANIC_TRUSTED_PROXY_CIDRS` peers. |
| `PANIC_TRUSTED_PROXY_CIDRS` | `127.0.0.1/32,::1/128` | Reverse proxies allowed to set the client-IP header, e.g. `192.0.2.10/32,2001:db8::10/128`. |
| `PANIC_PROXY_IP_HEADER` | `X-Forwarded-For` | `X-Forwarded-For` (right-most untrusted hop wins) or `Forwarded`. There is no `X-Real-IP` option: panic-web never sets it, and a single-value header cannot describe a multi-hop chain. |
| `PANIC_UNTRUSTED_PEER_POLICY` | `default` | `default` (unknown-location, Default zone) or `reject` (`403 UNTRUSTED_PEER`, except loopback `health`/`version`) when the direct peer is not a trusted proxy (AR-5.3). |
| `PANIC_XFF_MAX_HOPS` | `16` | Only the right-most this-many hops of the proxy header are considered. |
| `PANIC_XFF_MAX_BYTES` | `4096` | A proxy header longer than this is truncated from the left. |
| `PANIC_SECURE_PROXY_SSL_HEADER` | `false` | Trust `X-Forwarded-Proto: https` from the proxy. |
| `PANIC_SECURE_SSL_REDIRECT` | `false` | Redirect HTTP to HTTPS in Django. |
| `PANIC_HSTS_SECONDS` | `0` | `Strict-Transport-Security` max-age (enable once TLS is permanent). |

## Authentication & sessions

| Variable | Default | Description |
|---|---|---|
| `PANIC_SESSION_AGE_S` | `28800` | Session lifetime (s). |
| `PANIC_SESSION_COOKIE_SECURE` | `true` in prod | `Secure` flag on session and CSRF cookies. |
| `PANIC_AUTH_LOCAL_ENABLED` | `true` | Allow local password sign-in (bootstrap admin). |
| `PANIC_BOOTSTRAP_ADMIN_USER` | *(empty)* | Local Global Admin created/updated on first sign-in attempt. |
| `PANIC_BOOTSTRAP_ADMIN_PASSWORD` | *(empty)* | Its password (hashed at rest; use `PANIC_BOOTSTRAP_ADMIN_PASSWORD_FILE`). |

### OIDC / SSO

| Variable | Default | Description |
|---|---|---|
| `PANIC_OIDC_ENABLED` | `false` | Show "Sign in with …" and enable `/auth/oidc/*`. |
| `PANIC_OIDC_PROVIDER_NAME` | `Single Sign-On` | Button label. |
| `PANIC_OIDC_ISSUER` | *(empty)* | Issuer URL, e.g. `https://idp.example.com/realms/ops`; used for discovery and `iss` validation. |
| `PANIC_OIDC_CLIENT_ID` | *(empty)* | Client id (also the expected `aud`). |
| `PANIC_OIDC_CLIENT_SECRET` | *(empty)* | Client secret (use `_FILE`). |
| `PANIC_OIDC_AUTHORIZE_URL` | discovered | Override the authorization endpoint. |
| `PANIC_OIDC_TOKEN_URL` | discovered | Override the token endpoint. |
| `PANIC_OIDC_USERINFO_URL` | discovered | Override the userinfo endpoint (claims merged over the ID token). |
| `PANIC_OIDC_REDIRECT_URI` | *(empty)* | Must be `https://<panic host><PANIC_BASE_PATH>/auth/oidc/callback`, e.g. `https://ops.example.com/panic/auth/oidc/callback`. |
| `PANIC_OIDC_SCOPES` | `openid profile email groups` | Requested scopes. |
| `PANIC_OIDC_USERNAME_CLAIM` | `preferred_username` | Claim used as PANIC username. |
| `PANIC_OIDC_DISPLAY_NAME_CLAIM` | `name` | Claim used as display name. |
| `PANIC_OIDC_TIMEOUT_S` | `5` | HTTP timeout to the IdP. |

### LDAP / LDAPS

| Variable | Default | Description |
|---|---|---|
| `PANIC_LDAP_ENABLED` | `false` | Try LDAP bind for username/password sign-ins (after local accounts). |
| `PANIC_LDAP_URI` | *(empty)* | e.g. `ldaps://ldap.example.com`. |
| `PANIC_LDAP_START_TLS` | `false` | Upgrade `ldap://` with StartTLS. |
| `PANIC_LDAP_CA_CERT_FILE` | *(system store)* | CA bundle for certificate validation (always required). |
| `PANIC_LDAP_BIND_DN` | *(empty)* | Service account DN for user/group search (empty = anonymous). |
| `PANIC_LDAP_BIND_PASSWORD` | *(empty)* | Service account password (use `_FILE`). |
| `PANIC_LDAP_USER_BASE_DN` | *(empty)* | e.g. `ou=people,dc=example,dc=com`. |
| `PANIC_LDAP_USER_FILTER` | `(uid={username})` | `{username}` is RFC 4515-escaped. AD: `(sAMAccountName={username})`. |
| `PANIC_LDAP_USERNAME_ATTR` | `uid` | Attribute used as PANIC username. |
| `PANIC_LDAP_DISPLAY_NAME_ATTR` | `displayName` | Display name attribute. |
| `PANIC_LDAP_TIMEOUT_S` | `5` | Connect/receive timeout. |

External identity (OIDC and LDAP) is for authentication only (ADR-0001 decision 11):
there is no group -> RBAC/team mapping. A first external sign-in creates the user with no
permissions and no teams; a later sign-in only refreshes `display_name` and `last_login_at`.
Permissions and team membership are granted solely on the `/settings/users` page.

## Security hardening

| Variable | Default | Description |
|---|---|---|
| `PANIC_CSP` | built-in strict policy | Override the `Content-Security-Policy` header. |
| `PANIC_RATE_LIMIT_ENABLED` | `true` | Per-client-IP limits (`429` + `Retry-After`). |
| `PANIC_RATE_LIMIT_LOGIN` | `10/60` | `count/seconds` for sign-in requests (`POST /api/v1/auth/login`, OIDC login), per client IP and per submitted username. |
| `PANIC_RATE_LIMIT_API` | `300/60` | `count/seconds` for state-changing `/api/*` requests. |

Rate-limit counters live in MongoDB's `rate_limits` collection, shared by every
worker/node automatically -- there is no separate cache setting.

## MongoDB

See [`DATA_MODEL.md`](../Architecture/DATA_MODEL.md) §2. `panic_server.store` is the only package
that opens a connection.

| Variable | Default | Description |
|---|---|---|
| `PANIC_MONGO_URI` | *(empty; required)* | `mongodb://` / `mongodb+srv://` URI. Replica set, TLS, `authSource`, read preference and timeouts go in the URI; the database is the URI path component (default `panic`). Use `PANIC_MONGO_URI_FILE` to keep credentials out of the environment. |
| `PANIC_ZONE_CACHE_TTL_S` | `10` | How long the repository caches the full Security Zone set per process. |
| `PANIC_AUDIT_RETENTION_DAYS` | `365` | `audit_log` TTL, in days. `0` disables expiry (no TTL index). |
| `PANIC_TEST_MONGO_URI` | *(empty)* | Test-only override so `pytest` never touches a dev/prod database; falls back to `PANIC_MONGO_URI`, then the local dev-mongo container. |

## UI read views

See [`API.md`](../Architecture/API.md) §4.2 and [`DATA_MODEL.md`](../Architecture/DATA_MODEL.md) §4.7.

| Variable | Default | Description |
|---|---|---|
| `PANIC_NAV_MAX_DASHBOARDS` | `100` | Cap on `GET /api/v1/ui/bootstrap`'s `nav.dashboards`. |
| `PANIC_LIST_WIDGET_MAX_ITEMS` | `200` | Cap on a LIST widget's `item_ids` on `GET /api/v1/ui/dashboards/{id}`; `truncated: true` past this. |
| `PANIC_LIST_MAX_ITEMS` | `500` | Hard cap on an endpoint list's `item_ids` (DATA_MODEL.md §3); enforced by `PUT /api/v1/lists/{id}` and `GET /api/v1/lists/{id}`'s resolved `items`. |

## panic-web image

panic-web serves the SPA and proxies **only** the allow-listed paths in
`Application/Web/proxy-paths.json` to panic-server (AR-6.4); `/metrics` is never proxied.

| Variable | Default | Description |
|---|---|---|
| `PANIC_SERVER_URL` | *(required)* | panic-server origin, `scheme://host[:port]` with no path, e.g. `http://panic-server:8210`. Validated at start; `PANIC_SERVER_URL_FILE` is also accepted. The dev proxy (`./panic start`) reads it too (default `http://127.0.0.1:8121`). |
| `PANIC_BASE_PATH` | *(empty: `/`)* | URL prefix, as on the server (must match). Everything is served below it and forwarded to the server with the prefix; the SPA learns it from `<base href>`, rewritten per request, so one image serves any prefix. Outside the prefix only `/healthz` answers (`<prefix>` alone redirects to `<prefix>/`). `./panic start` serves the dev UI under it too. |

panic-web appends the browser's address to `X-Forwarded-For`; list panic-web's address in the
server's `PANIC_TRUSTED_PROXY_CIDRS` so the server resolves the real client IP and zone.

## Compose and development

| Variable | Default | Description |
|---|---|---|
| `PANIC_IMAGE_PREFIX` / `PANIC_IMAGE_TAG` | `panic-local` / `latest` | Image names used by the compose files. |
| `PANIC_SERVER_REPLICAS` | `1` | panic-server replicas in `compose.yaml` (any replica serves any session). |
| `PANIC_WEB_PUBLISH` | `8080` | Host port for panic-web. |
| `PANIC_SERVER_PUBLISH` | `8210` | Host port in `compose.standalone.server.yaml`. |
| `PANIC_ENV_FILE` | `panic.env` | Env file for `compose.standalone.server.yaml`. |
| `PANIC_WEB_PORT` | `8120` | `./panic start` dev web server port. |
| `PANIC_WEB_ALLOWED_HOSTS` | *(this machine's hostname and FQDN)* | Extra hostnames the Vite dev server accepts (comma-separated; leading dot = subdomains). |

## Removed settings

Earlier versions read these. They are ignored now; delete them from env files.

| Variable | Why |
|---|---|
| `PANIC_DB_ENGINE`, `PANIC_DB_HOST`, `PANIC_DB_PORT`, `PANIC_DB_NAME`, `PANIC_DB_USER`, `PANIC_DB_PASSWORD`, `PANIC_DB_CONN_MAX_AGE`, `PANIC_SQLITE_PATH` | No relational database: MongoDB only (`PANIC_MONGO_URI`). |
| `PANIC_STATIC_ROOT` | panic-server serves no static files; panic-web serves the SPA. |
| `PANIC_AUTO_SEED` | Replaced by `PANIC_SEED_ON_START`. |
| `PANIC_AUTH_MODE` | The simulator auth mode is gone; local, LDAP and OIDC are switched on individually. |
| `PANIC_OIDC_GROUPS_CLAIM`, `PANIC_LDAP_GROUP_BASE_DN`, `PANIC_LDAP_GROUP_FILTER`, `PANIC_RBAC_ADMIN_GROUPS`, `PANIC_RBAC_GLOBAL_CONTRIB_GROUPS`, `PANIC_RBAC_TEAM_CONTRIB_GROUPS`, `PANIC_RBAC_TEAM_GROUP_MAP`, `PANIC_RBAC_TEAM_GROUP_PREFIX` | External identity is authentication only: permissions and teams are set on `/settings/users`. |
| `PANIC_CACHE_URL` | Rate limits and sessions live in MongoDB. |

## Reserved

`PANIC_CATALOG_MODERATION_MODE` appears in `.env.example` but is not
yet read by the server.

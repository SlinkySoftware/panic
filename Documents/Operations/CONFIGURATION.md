# PANIC Configuration Reference

Every setting comes from the environment (AR-3.1). Any variable may instead be supplied as
`<NAME>_FILE` pointing at a file whose contents are the value (Docker / Kubernetes secrets); the
`_FILE` form wins when both are set. Booleans accept `true/false/1/0/yes/no/on/off`; lists are
comma-separated. Source of truth: `Application/Server/panic_server/settings.py` and
`Build/Containers/server/entrypoint.sh` (a test fails if a setting is missing from this page).

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
| `PANIC_TZ` | `UTC` | Display time zone. |
| `PANIC_LOG_LEVEL` | `INFO` | Python log level. |
| `PANIC_LOG_FORMAT` | `json` | `json` (structured, with request id) or `console`. |
| `PANIC_SERVER_BIND` | `0.0.0.0:8120` (`./panic`), `0.0.0.0:8210` (container) | Gunicorn / dev server bind address. |

## Database

PANIC has no relational database (T-S6-04 removed the Django ORM / SQLite-or-PostgreSQL store
entirely; see [`DATA_MODEL.md`](../Architecture/DATA_MODEL.md)). All domain data, sessions and
rate limits live in MongoDB -- see the "MongoDB" section below.

| Variable | Default | Description |
|---|---|---|
| `PANIC_MIGRATE_ON_START` | `true` | Container entrypoint runs `migrate --noinput` (a no-op: there are no Django-ORM migrations left). |
| `PANIC_SEED_ON_START` | `never` in prod, else `if-empty` | Container entrypoint seeding of the demo fixtures: `if-empty` or `never`. |

## Gunicorn (container)

| Variable | Default | Description |
|---|---|---|
| `PANIC_GUNICORN_WORKERS` | `2` | Worker processes. |
| `PANIC_GUNICORN_THREADS` | `4` | Threads per worker. |
| `PANIC_GUNICORN_TIMEOUT` | `30` | Worker timeout (s). |
| `PANIC_GUNICORN_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Gunicorn `--forwarded-allow-ips` (scheme headers only; client IPs use `PANIC_TRUSTED_PROXY_CIDRS`). |

## Reverse proxy & Security Zones

| Variable | Default | Description |
|---|---|---|
| `PANIC_TRUST_PROXY_HEADERS` | `true` | Honour the client-IP header **only** from `PANIC_TRUSTED_PROXY_CIDRS` peers. |
| `PANIC_TRUSTED_PROXY_CIDRS` | `127.0.0.1/32,::1/128` | Reverse proxies allowed to set the client-IP header, e.g. `192.0.2.10/32,2001:db8::10/128`. |
| `PANIC_PROXY_IP_HEADER` | `X-Forwarded-For` | `X-Forwarded-For` (right-most untrusted hop wins) or `Forwarded`. The `X-Real-IP` option is removed (T-S6-04): panic-web never sets it and the hop-chain resolver only understands the two forms above. |
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
| `PANIC_OIDC_REDIRECT_URI` | *(empty)* | Must be `https://<panic host>/auth/oidc/callback`. |
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

External identity (OIDC and LDAP) is for authentication only (T-S6-04, ADR-0001 decision 11):
there is no group -> RBAC/team mapping. A first external sign-in creates the user with no
permissions and no teams; a later sign-in only refreshes `display_name` and `last_login_at`.
Permissions and team membership are granted solely on the `/settings/users` page.

## Security hardening

| Variable | Default | Description |
|---|---|---|
| `PANIC_CSP` | built-in strict policy | Override the `Content-Security-Policy` header. |
| `PANIC_RATE_LIMIT_ENABLED` | `true` | Per-client-IP limits (`429` + `Retry-After`). |
| `PANIC_RATE_LIMIT_LOGIN` | `10/60` | `count/seconds` for `POST /login`. |
| `PANIC_RATE_LIMIT_API` | `300/60` | `count/seconds` for state-changing `/api/*` requests. |

Rate-limit counters live in MongoDB's `rate_limits` collection (T-S6-04), shared by every
worker/node automatically -- there is no separate cache setting.

## MongoDB (Stage 6)

See [`DATA_MODEL.md`](../Architecture/DATA_MODEL.md) §2. `panic_server.store` is the only package
that opens a connection.

| Variable | Default | Description |
|---|---|---|
| `PANIC_MONGO_URI` | *(empty; required)* | `mongodb://` / `mongodb+srv://` URI. Replica set, TLS, `authSource`, read preference and timeouts go in the URI; the database is the URI path component (default `panic`). Use `PANIC_MONGO_URI_FILE` to keep credentials out of the environment. |
| `PANIC_ZONE_CACHE_TTL_S` | `10` | How long the repository caches the full Security Zone set per process. |
| `PANIC_AUDIT_RETENTION_DAYS` | `365` | `audit_log` TTL, in days. `0` disables expiry (no TTL index). |
| `PANIC_TEST_MONGO_URI` | *(empty)* | Test-only override so `pytest` never touches a dev/prod database; falls back to `PANIC_MONGO_URI`, then the local dev-mongo container. |

## UI read views (Stage 6, T-S6-06)

See [`API.md`](../Architecture/API.md) §4.2 and [`DATA_MODEL.md`](../Architecture/DATA_MODEL.md) §4.7.

| Variable | Default | Description |
|---|---|---|
| `PANIC_NAV_MAX_DASHBOARDS` | `100` | Cap on `GET /api/v1/ui/bootstrap`'s `nav.dashboards`. |
| `PANIC_LIST_WIDGET_MAX_ITEMS` | `200` | Cap on a LIST widget's `item_ids` on `GET /api/v1/ui/dashboards/{id}`; `truncated: true` past this. |
| `PANIC_LIST_MAX_ITEMS` | `500` | Hard cap on an endpoint list's `item_ids` (DATA_MODEL.md §3); enforced by `PUT /api/v1/lists/{id}` and `GET /api/v1/lists/{id}`'s resolved `items`. |

## Reserved

`PANIC_CATALOG_MODERATION_MODE` appears in `.env.example` but is not
yet read by the server.

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
| `PANIC_ENV` | `dev` | `dev`, `test` or `prod`. `prod` enforces a strong secret key, `session` auth, secure cookies, and disables auto-seeding. |
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

| Variable | Default | Description |
|---|---|---|
| `PANIC_DB_ENGINE` | `sqlite` | `sqlite` (single node) or `postgresql` (HA; install the `postgres` extra). |
| `PANIC_SQLITE_PATH` | `.run/panic.sqlite3` (container: `/data/panic.sqlite3`) | SQLite file (`:memory:` for throwaway runs). |
| `PANIC_DB_HOST` | `127.0.0.1` | PostgreSQL host. |
| `PANIC_DB_PORT` | `5432` | PostgreSQL port. |
| `PANIC_DB_NAME` | `panic` | PostgreSQL database. |
| `PANIC_DB_USER` | `panic` | PostgreSQL role. |
| `PANIC_DB_PASSWORD` | *(empty)* | PostgreSQL password (use `PANIC_DB_PASSWORD_FILE`). |
| `PANIC_DB_CONN_MAX_AGE` | `60` | Persistent connection lifetime in seconds. |
| `PANIC_AUTO_SEED` | `true` unless prod | Seed canonical demo fixtures on the first request when the database is empty. |
| `PANIC_MIGRATE_ON_START` | `true` | Container entrypoint runs `migrate --noinput`. |
| `PANIC_SEED_ON_START` | `if-empty` | Container entrypoint seeding: `if-empty` or `never`. |

## Static assets & Gunicorn (container)

| Variable | Default | Description |
|---|---|---|
| `PANIC_STATIC_ROOT` | `Application/Server/staticfiles` (container: `/app/staticfiles`) | `collectstatic` target. |
| `PANIC_SERVE_STATIC` | `true` | Serve `/static/` from `PANIC_STATIC_ROOT` when `DEBUG` is off. Set `false` if the reverse proxy serves it. |
| `PANIC_GUNICORN_WORKERS` | `2` | Worker processes. |
| `PANIC_GUNICORN_THREADS` | `4` | Threads per worker. |
| `PANIC_GUNICORN_TIMEOUT` | `30` | Worker timeout (s). |
| `PANIC_GUNICORN_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Gunicorn `--forwarded-allow-ips` (scheme headers only; client IPs use `PANIC_TRUSTED_PROXY_CIDRS`). |

## Reverse proxy & Security Zones

| Variable | Default | Description |
|---|---|---|
| `PANIC_TRUST_PROXY_HEADERS` | `true` | Honour the client-IP header **only** from `PANIC_TRUSTED_PROXY_CIDRS` peers. |
| `PANIC_TRUSTED_PROXY_CIDRS` | `127.0.0.1/32,::1/128` | Reverse proxies allowed to set the client-IP header, e.g. `192.0.2.10/32,2001:db8::10/128`. |
| `PANIC_PROXY_IP_HEADER` | `X-Forwarded-For` | `X-Forwarded-For` (right-most untrusted hop wins) or `X-Real-IP`. |
| `PANIC_SECURE_PROXY_SSL_HEADER` | `false` | Trust `X-Forwarded-Proto: https` from the proxy. |
| `PANIC_SECURE_SSL_REDIRECT` | `false` | Redirect HTTP to HTTPS in Django. |
| `PANIC_HSTS_SECONDS` | `0` | `Strict-Transport-Security` max-age (enable once TLS is permanent). |

## Authentication & sessions

| Variable | Default | Description |
|---|---|---|
| `PANIC_AUTH_MODE` | `simulator` (dev/test), `session` (prod) | `simulator` (no login, RBAC simulator) or `session` (real sign-in). `simulator` is rejected in prod. |
| `PANIC_DEV_SIMULATOR_ENABLED` | `true` in simulator mode | Allows the Source IP / Zone / active-user simulator. When `false`, user switching and reset return `403`. |
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
| `PANIC_OIDC_GROUPS_CLAIM` | `groups` | Claim holding group / role names (list or space/comma-separated string). |
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
| `PANIC_LDAP_GROUP_BASE_DN` | *(empty)* | Group search base (empty = no group lookup). |
| `PANIC_LDAP_GROUP_FILTER` | `(member={user_dn})` | `{user_dn}` / `{username}` are escaped. |
| `PANIC_LDAP_GROUP_NAME_ATTR` | `cn` | Group name attribute. |
| `PANIC_LDAP_TIMEOUT_S` | `5` | Connect/receive timeout. |

### Group → RBAC / Team mapping (OIDC and LDAP)

Group names are compared case-insensitively; an LDAP DN matches on its first RDN value.
Permissions and team memberships are re-synchronised on every external sign-in.

| Variable | Default | Description |
|---|---|---|
| `PANIC_RBAC_ADMIN_GROUPS` | *(empty)* | Groups granted `GLOBAL_ADMIN` (+ both contributor flags). |
| `PANIC_RBAC_GLOBAL_CONTRIB_GROUPS` | *(empty)* | Groups granted `CAN_ADD_GLOBAL`. |
| `PANIC_RBAC_TEAM_CONTRIB_GROUPS` | *(empty)* | Groups granted `CAN_ADD_TEAM`. |
| `PANIC_RBAC_TEAM_GROUP_MAP` | *(empty)* | `external-group=TEAMCODE` pairs, e.g. `network-engineers=NETOPS`. |
| `PANIC_RBAC_TEAM_GROUP_PREFIX` | *(empty)* | Groups named `<prefix><teamcode>` join that team, e.g. prefix `panic-team-`. |

## Security hardening

| Variable | Default | Description |
|---|---|---|
| `PANIC_CSP` | built-in strict policy | Override the `Content-Security-Policy` header. |
| `PANIC_RATE_LIMIT_ENABLED` | `true` | Per-client-IP limits (`429` + `Retry-After`). |
| `PANIC_RATE_LIMIT_LOGIN` | `10/60` | `count/seconds` for `POST /login`. |
| `PANIC_RATE_LIMIT_API` | `300/60` | `count/seconds` for state-changing `/api/*` requests. |
| `PANIC_CACHE_URL` | *(local memory)* | `redis://…` shared cache for rate limits across workers/nodes (install the `redis` extra). |

## Reserved

`PANIC_CATALOG_MODERATION_MODE` appears in `.env.example` but is not
yet read by the server.

# PANIC Deployment Guide

Companion to [`CONFIGURATION.md`](CONFIGURATION.md). All hostnames and addresses below are
documentation placeholders (`example.com`, RFC 5737 `192.0.2.0/24`, RFC 3849 `2001:db8::/32`).

## 1. Topologies

| Topology | Database | When |
|---|---|---|
| Single node | SQLite on a persistent volume (`/data/panic.sqlite3`) | Small teams, one container / VM. |
| HA | PostgreSQL 17 (managed or the compose `postgres` profile) | Several PANIC replicas behind a load balancer. |

Each request reloads portal state from the database and writes back only changed entities, so
any number of Gunicorn workers or replicas can share one PostgreSQL database. For HA also set
`PANIC_CACHE_URL=redis://cache.example.com:6379/0` so rate-limit counters are shared.

## 2. Docker Compose

```bash
# 1. Environment file (never commit it)
cat > /srv/panic/panic.env <<'ENV'
PANIC_ENV=prod
PANIC_DJANGO_SECRET_KEY_FILE=/run/secrets/panic_secret_key
PANIC_ALLOWED_HOSTS=panic.example.com
PANIC_CSRF_TRUSTED_ORIGINS=https://panic.example.com
PANIC_TRUSTED_PROXY_CIDRS=192.0.2.10/32,2001:db8::10/128
PANIC_SECURE_PROXY_SSL_HEADER=true
PANIC_BOOTSTRAP_ADMIN_USER=panic-admin
PANIC_BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/panic_admin_password
ENV

# 2a. Single node (SQLite)
docker compose --env-file /srv/panic/panic.env -f Build/Containers/compose.yaml up -d --build

# 2b. PostgreSQL 17 (add PANIC_DB_ENGINE=postgresql and PANIC_DB_PASSWORD to the env file)
docker compose --env-file /srv/panic/panic.env -f Build/Containers/compose.yaml --profile postgres up -d --build
```

The image runs as the unprivileged `panic` user (uid 10001) on a read-only root filesystem. On
start the entrypoint runs `migrate --noinput` and `panic_seed --if-empty`, then Gunicorn. The
container `HEALTHCHECK` polls `GET /api/v1/health`, which returns `503` when the database is
unreachable. Mount secrets (e.g. compose `secrets:`) and refer to them via `*_FILE` variables.

Validate configuration before deploying: `docker compose -f Build/Containers/compose.yaml config -q`.

## 3. Reverse proxy & client IP

PANIC derives the jump host's Security Zone from the client IP, so the proxy must pass it and
PANIC must trust **only** that proxy:

- Set `PANIC_TRUSTED_PROXY_CIDRS` to the proxy's addresses. Headers from any other peer are ignored
  (spoofed `X-Forwarded-For` has no effect).
- With `X-Forwarded-For`, PANIC uses the right-most hop that is not itself a trusted proxy.
- Terminate TLS at the proxy, send `X-Forwarded-Proto`, set `PANIC_SECURE_PROXY_SSL_HEADER=true`,
  and once stable `PANIC_HSTS_SECONDS=31536000`.

nginx example:

```nginx
server {
    listen 443 ssl;
    server_name panic.example.com;
    location / {
        proxy_pass http://127.0.0.1:8210;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Verify with `curl -sI https://panic.example.com/api/v1/health`: the `X-Client-IP` and
`X-Security-Zone` response headers show what PANIC resolved.

## 4. Authentication

1. Start with the local bootstrap admin (`PANIC_BOOTSTRAP_ADMIN_*`) and sign in at `/login`.
2. Configure OIDC (`PANIC_OIDC_*`, redirect URI `https://panic.example.com/auth/oidc/callback`)
   and/or LDAP (`PANIC_LDAP_*`), plus the `PANIC_RBAC_*` group mappings.
3. Optionally disable local sign-in with `PANIC_AUTH_LOCAL_ENABLED=false` once SSO works.

`PANIC_ENV=prod` refuses to start with the simulator auth mode or a weak secret key.

## 5. Backup & restore

Portable JSON (sites, teams, zones, users without credentials, catalog, lists, dashboards, settings):

```bash
# Backup
docker compose -f Build/Containers/compose.yaml exec server \
  python -m django panic_export > panic-$(date +%F).json
# Shared configuration only (no users / PERSONAL items) for promoting between environments
docker compose -f Build/Containers/compose.yaml exec server python -m django panic_export --shared-only

# Restore (upsert by id); --replace wipes the database first
docker compose -f Build/Containers/compose.yaml exec -T server \
  python -m django panic_import - < panic-2026-11-14.json
```

Global Admins can also download `GET /api/v1/export`. For full fidelity (audit log, sessions)
back up the database itself: copy `/data/panic.sqlite3` while stopped, or `pg_dump` PostgreSQL.

## 6. Monitoring

- `GET /api/v1/health`: liveness + database status (`200` / `503`).
- `GET /api/v1/version`: build version and stage.
- `GET /metrics`: Prometheus exposition (`panic_http_requests_total`,
  `panic_http_request_duration_seconds`). Restrict it to the monitoring network at the proxy.

```yaml
scrape_configs:
  - job_name: panic
    metrics_path: /metrics
    static_configs:
      - targets: ["panic.example.com:8210"]
```

Logs are JSON on stdout, one line per request with `request_id` (echoed in `X-Request-ID`).

## 7. Upgrades

Pull/build the new image and `docker compose up -d`. Migrations run automatically on start
(`PANIC_MIGRATE_ON_START=true`); with several replicas, set it to `false` on all but one or run
`python -m django migrate` as a one-off job first. Take a `panic_export` backup before upgrading.

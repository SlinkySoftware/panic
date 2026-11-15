# PANIC Deployment Guide

Stage 6 runs as two images plus MongoDB. Every setting is an environment variable, listed in
[`CONFIGURATION.md`](CONFIGURATION.md). Examples use reserved names and addresses only
(`example.com`, RFC 5737, RFC 3849). There is no upgrade path from Stage 4: it was never deployed.

## 1. Topology

```
browser ──► [TLS proxy / L7 LB] ──► panic-web (nginx, :8080) ──► panic-server ×N (:8210) ──► MongoDB
             optional                SPA + allow-listed proxy     API, stateless          replica set
```

- **panic-web** serves the SPA and forwards only the paths in `Application/Web/proxy-paths.json`
  (AR-6.4). `/metrics` and every other API path return `404` at web.
- **panic-server** is stateless: sessions and rate limits live in MongoDB, so any replica serves any
  request and replicas can restart without signing anyone out.
- **Zones:** PANIC resolves each request's client IP to a Security Zone, which decides which items
  are reachable. Every hop that adds `X-Forwarded-For` must be trusted explicitly (§3).
- panic-web can sit in a different network zone from panic-server (`compose.standalone.web.yaml`
  and `compose.standalone.server.yaml`), for example web in a DMZ and server next to MongoDB.

## 2. Docker Compose

```bash
# 1. Environment file (never commit it). Minimum for production:
cat > /etc/panic/panic.env <<'EOF'
PANIC_ENV=prod
PANIC_DJANGO_SECRET_KEY_FILE=/run/secrets/panic_secret_key
PANIC_MONGO_URI_FILE=/run/secrets/panic_mongo_uri
PANIC_ALLOWED_HOSTS=panic.example.com
PANIC_CSRF_TRUSTED_ORIGINS=https://panic.example.com
PANIC_TRUSTED_PROXY_CIDRS=192.0.2.0/28
PANIC_SECURE_PROXY_SSL_HEADER=true
PANIC_BOOTSTRAP_ADMIN_USER=admin
PANIC_BOOTSTRAP_ADMIN_PASSWORD_FILE=/run/secrets/panic_admin_password
EOF

# 2a. Full stack against your MongoDB, two server replicas
PANIC_SERVER_REPLICAS=2 docker compose --env-file /etc/panic/panic.env \
  -f Build/Containers/compose.yaml up -d

# 2b. Dev / demo with a bundled single-node MongoDB (not for production)
docker compose --env-file /etc/panic/panic.env -f Build/Containers/compose.yaml --profile demo-mongo up -d
```

Both images run as non-root users on a read-only root filesystem, and both have a `HEALTHCHECK`. The
server's checks `/api/v1/health?ready=1`, which includes a MongoDB ping, so a replica that loses the
database turns unhealthy. Published images: `panic-web` and `panic-server`, tagged `:main`,
`:sha-<short>`, and `:X.Y.Z` / `:X.Y` / `:latest` for releases.

### Replicas and migrations

On start every server replica runs `panic_ensure_indexes` (idempotent), then `panic_migrate` when
`PANIC_MIGRATE_ON_START=true` (the default). Migrations are idempotent, but `panic_migrate` takes no
lock, so with several replicas migrate from one place. Set it to `false` on the replicas, then run a
one-off init before the rollout:

```bash
docker run --rm --env-file /etc/panic/panic.env <registry>/<owner>/panic-server:X.Y.Z init
```

## 3. Trusted proxies and client IP (worked example)

PANIC walks `X-Forwarded-For` from the right. It skips hops whose address is in
`PANIC_TRUSTED_PROXY_CIDRS`, and the first address that is not trusted is the client
(`FIRST_UNTRUSTED_HOP`). Headers from an untrusted direct peer are ignored, so a spoofed
`X-Forwarded-For` has no effect.

Four tiers:

| Tier | Address | Adds to `X-Forwarded-For` |
|---|---|---|
| Jump host (the "browser") | `198.51.100.23` | – |
| TLS proxy / L7 load balancer | `192.0.2.5` | `198.51.100.23` |
| panic-web | `192.0.2.10` | `192.0.2.5` |
| panic-server | `192.0.2.20` | – (reads the header) |

The server receives a request from peer `192.0.2.10` with `X-Forwarded-For: 198.51.100.23, 192.0.2.5`.
With `PANIC_TRUSTED_PROXY_CIDRS=192.0.2.5/32,192.0.2.10/32`, it trusts the peer, skips `192.0.2.5`
and resolves the client to `198.51.100.23`. That address then matches the zone whose CIDR contains it.

- Trust **only** the proxy tiers. A CIDR that also covers jump hosts lets those jump hosts choose
  their own zone.
- **L4 load balancers** (TCP pass-through) add no header. If they also SNAT, every request arrives from
  the load balancer's address and all clients land in one zone. Use PROXY protocol into the TLS proxy
  or an L7 load balancer in front of panic-web, or route without SNAT.
- Terminate TLS in front of panic-web, send `X-Forwarded-Proto`, set
  `PANIC_SECURE_PROXY_SSL_HEADER=true`, and once TLS is permanent set `PANIC_HSTS_SECONDS=31536000`.
- **Verify** as a Global Admin at `/settings/client-ip`. It shows each hop, the trust decision, the
  resolved IP and the zone. Every response also carries `X-Client-IP` and `X-Security-Zone`.

## 4. MongoDB

- **URI:** put everything in `PANIC_MONGO_URI` (prefer `_FILE`). The database is the URI path:

  ```
  mongodb://panic_app:<password>@db1.example.com,db2.example.com,db3.example.com/panic
    ?replicaSet=rs0&tls=true&tlsCAFile=/run/secrets/mongo_ca.pem&authSource=admin
    &readPreference=primary&w=majority&retryWrites=true
  ```

- **Topology:** use a three-member replica set for production. The bundled `demo-mongo` profile is a
  single node without authentication.
- **Least-privilege role:** the application needs read/write on its own database and index management,
  nothing cluster-wide:

  ```javascript
  use admin
  db.createRole({ role: "panicApp", privileges: [
      { resource: { db: "panic", collection: "" },
        actions: ["find", "insert", "update", "remove", "createIndex", "dropIndex", "listIndexes",
                  "createCollection", "listCollections", "collStats"] } ], roles: [] })
  db.createUser({ user: "panic_app", pwd: passwordPrompt(), roles: ["panicApp"] })
  ```

## 5. Authentication

1. Start with the local bootstrap admin (`PANIC_BOOTSTRAP_ADMIN_*`) and sign in at `/login`.
2. Configure LDAP (`PANIC_LDAP_*`) and/or OIDC (`PANIC_OIDC_*`, redirect URI
   `https://panic.example.com/auth/oidc/callback`, one per panic-web hostname). To restrict who can
   sign in, put a group condition in `PANIC_LDAP_USER_FILTER`, or use the IdP's access policy.
3. External sign-in is authentication only. A new user gets no permissions; grant permissions and
   teams on `/settings/users`.
4. Optionally disable local sign-in with `PANIC_AUTH_LOCAL_ENABLED=false` once SSO works.

`PANIC_ENV=prod` refuses to start with a weak or placeholder secret key.

## 6. Backup & restore

- **Full fidelity** (including audit log and sessions): back up MongoDB itself.

  ```bash
  mongodump --uri "$PANIC_MONGO_URI" --gzip --archive=panic-$(date +%F).archive.gz
  mongorestore --uri "$PANIC_MONGO_URI" --gzip --archive=panic-2026-11-14.archive.gz --drop
  ```

- **Provisioning / promotion** (portable JSON: sites, teams, zones, users without credentials,
  catalog, lists, dashboards, settings) with `panic_export`:

  ```bash
  docker compose -f Build/Containers/compose.yaml exec server python -m django panic_export > panic.json
  docker compose -f Build/Containers/compose.yaml exec server python -m django panic_export --shared-only
  docker compose -f Build/Containers/compose.yaml exec -T server python -m django panic_import - < panic.json
  ```

  `panic_import` upserts by id; `--replace` wipes the portal data first. Global Admins can also
  download `GET /api/v1/export` (Settings → Export).

## 7. Monitoring

- `GET /healthz` on panic-web: nginx is up.
- `GET /api/v1/health` gives liveness; `?ready=1` adds a MongoDB ping (`200` or `503`).
- `GET /api/v1/version`: build version.
- `GET /metrics` on panic-server's port only (never through panic-web):
  `panic_http_requests_total`, `panic_http_request_duration_seconds`.

```yaml
scrape_configs:
  - job_name: panic-server
    metrics_path: /metrics
    static_configs:
      - targets: ["panic-server.example.com:8210"]
```

Logs are JSON on stdout, one line per request, with `request_id` (echoed in `X-Request-ID`).

## 8. Upgrades

Take a `mongodump`, pull the new tags, then run `docker compose up -d`. Indexes and migrations run on
start (§2). panic-web and panic-server from the same release are tested together. Upgrade both.

## 9. Development

```bash
./panic setup     # venv, pinned Node, npm ci, .env
./panic start     # dev MongoDB container, server on :8121, Vite dev server on :8120 (this host's name allowed)
./panic test      # pytest (incl. Build/scripts), ruff, mypy, import-linter; web: cd Application/Web && npm test
Build/ci/container_smoke.sh   # build-and-run check of both images (needs the images built locally)
```

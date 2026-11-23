#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Joint smoke test of the built images (T-S6-12): browser -> panic-web -> 2x panic-server -> MongoDB.
#   PANIC_IMAGE_PREFIX / PANIC_IMAGE_TAG select the images (default panic-local/*:latest).
#   SMOKE_BASE_PATH runs the stack under a URL prefix (PANIC_BASE_PATH on both tiers, e.g. /panic).
# Proves: SPA + healthz served, /metrics and unlisted API paths 404 at web, sign-in through web, sessions
# work across both replicas (round-robin) and after a replica restart, and the server sees the browser's
# IP through the web tier (client-IP diagnostics: FIRST_UNTRUSTED_HOP with the client container's IP).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="panic-smoke-$$"
SUBNET_PREFIX="172.31.250"
CLIENT_IP="${SUBNET_PREFIX}.50"
# Inside the checkout, not /tmp: in CI the job runs in a container while `docker run -v` is resolved by the
# host daemon, and only the checkout (the runner's bind_workdir) is a real host path a sibling container can mount.
WORK="$ROOT/.run/smoke-$$"
mkdir -p "$WORK"
chmod 777 "$WORK"
ADMIN_PW="smoke-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
BASE="${SMOKE_BASE_PATH:-}"

cat > "$WORK/override.yaml" <<YAML
services:
  web:
    ports: !reset []
    environment:
      PANIC_BASE_PATH: "${BASE}"
    networks:
      default:
        ipv4_address: ${SUBNET_PREFIX}.10
  server:
    environment:
      PANIC_ENV: prod
      PANIC_BASE_PATH: "${BASE}"
      PANIC_DJANGO_SECRET_KEY: smoke-$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
      PANIC_ALLOWED_HOSTS: web,localhost
      PANIC_CSRF_TRUSTED_ORIGINS: http://web:8080
      PANIC_TRUSTED_PROXY_CIDRS: ${SUBNET_PREFIX}.10/32
      PANIC_BOOTSTRAP_ADMIN_USER: smoke-admin
      PANIC_BOOTSTRAP_ADMIN_PASSWORD: ${ADMIN_PW}
      PANIC_SEED_ON_START: never
      PANIC_RATE_LIMIT_ENABLED: "false"
      PANIC_SESSION_COOKIE_SECURE: "false"   # the smoke client talks plain HTTP to web
networks:
  default:
    ipam:
      config:
        - subnet: ${SUBNET_PREFIX}.0/24
YAML

compose() {
    PANIC_SERVER_REPLICAS=2 docker compose -p "$PROJECT" -f "$ROOT/Build/Containers/compose.yaml" \
        -f "$WORK/override.yaml" --profile demo-mongo "$@"
}
cleanup() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then compose logs --tail 60 || true; fi
    if [[ -n "${SMOKE_KEEP:-}" ]]; then echo "kept: project $PROJECT (override in $WORK)"; exit $rc; fi
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORK"
    exit $rc
}
trap cleanup EXIT

client() {  # run a shell snippet in a curl container at the fixed client IP; $WORK is /w (cookie jar)
    docker run --rm --network "${PROJECT}_default" --ip "$CLIENT_IP" -v "$WORK:/w" \
        -e ADMIN_PW="$ADMIN_PW" -e BASE="$BASE" --entrypoint sh docker.io/curlimages/curl:8.11.1 -ec "$1"
}

echo "== starting stack (web, 2x server, mongo)${BASE:+ under $BASE/}"
compose up -d --wait --wait-timeout 180

echo "== web tier, allow-list and sign-in"
client '
B=http://web:8080$BASE
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }
[ "$(code http://web:8080/healthz)" = 200 ]
curl -fsS $B/ | grep -q "q-app"
curl -fsS $B/ | grep -qF "<base href=\"$BASE/\">"
curl -fsS $B/catalog | grep -qF "<base href=\"$BASE/\">"      # SPA fallback, deep link
ASSET=$(curl -fsS $B/ | sed -n "s#.*src=\"\./\(assets/[^\"]*\.js\)\".*#\1#p" | head -1)
[ "$(code $B/$ASSET)" = 200 ]
if [ -n "$BASE" ]; then
  [ "$(curl -s -o /dev/null -w "%{http_code} %{redirect_url}" $B)" = "301 http://web:8080$BASE/" ]
  [ "$(code http://web:8080/)" = 404 ]                          # outside the prefix
  [ "$(code http://web:8080/api/v1/health)" = 404 ]
  [ "$(code http://web:8080/$ASSET)" = 404 ]
fi
[ "$(code $B/metrics)" = 404 ]
[ "$(code $B/api/v1/not-listed)" = 404 ]
[ "$(code $B/api/v1/health)" = 200 ]
[ "$(code $B/api/v1/ui/bootstrap)" = 401 ]
curl -fsS -c /w/jar -b /w/jar $B/api/v1/auth/csrf -o /dev/null
TOKEN=$(awk "\$6 == \"panic_csrftoken\" {print \$7}" /w/jar)
[ "$(awk "\$6 == \"panic_csrftoken\" {print \$3}" /w/jar)" = "$BASE/" ]   # cookie stays inside the prefix
curl -fsS -c /w/jar -b /w/jar -H "X-CSRFToken: $TOKEN" -H "Content-Type: application/json" \
  -d "{\"username\":\"smoke-admin\",\"password\":\"$ADMIN_PW\"}" $B/api/v1/auth/login -o /dev/null
for i in $(seq 1 20); do [ "$(code -b /w/jar $B/api/v1/ui/bootstrap)" = 200 ]; done
D=$(curl -fsS -b /w/jar -H "X-Forwarded-For: 198.51.100.77" $B/api/v1/admin/client-ip)
echo "$D" | grep -q "\"client_ip\": *\"'"$CLIENT_IP"'\""
echo "$D" | grep -q "\"decision\": *\"FIRST_UNTRUSTED_HOP\""
echo "client-ip ok: '"$CLIENT_IP"' via FIRST_UNTRUSTED_HOP"
'

echo "== both replicas served requests"
served=0
for c in $(compose ps -q server); do
    n=$(docker logs "$c" 2>&1 | grep -c '/api/v1/ui/bootstrap' || true)  # not grep -q: SIGPIPE + pipefail
    if [[ ${n:-0} -gt 0 ]]; then served=$((served + 1)); fi
done
[[ $served -eq 2 ]] || { echo "expected both server replicas to serve bootstrap, got $served" >&2; exit 1; }

echo "== session survives a replica restart"
docker restart "$(compose ps -q server | head -1)" >/dev/null
compose up -d --wait --wait-timeout 120 server >/dev/null
client 'for i in $(seq 1 10); do [ "$(curl -s -o /dev/null -w "%{http_code}" -b /w/jar http://web:8080$BASE/api/v1/ui/bootstrap)" = 200 ]; done'

echo "smoke ok"

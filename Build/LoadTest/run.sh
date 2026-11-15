#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# T-S6-14 load test on the development host: built images via compose (1x panic-web, 2x panic-server,
# 2 workers x 8 threads each) against the shared dev MongoDB container, in its own `panic_loadtest`
# database (the dev data in `panic` is never touched). Seeds `--profile loadtest`, mints one session per
# load user, then runs Locust headless: a steady run and a stress run. Results land in $OUT.
#   SKIP_BUILD=1  reuse panic-local/panic-{web,server}:latest
#   RAMP_S=120 STEADY_S=900 STRESS_S=180  durations (seconds)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${OUT:-$ROOT/Build/LoadTest/results/$(date +%Y%m%d-%H%M%S)}"
RAMP_S="${RAMP_S:-120}"; STEADY_S="${STEADY_S:-900}"; STRESS_S="${STRESS_S:-180}"
USERS=50
PROJECT="panic-loadtest"
SUBNET_PREFIX="172.31.251"
WEB_PORT="${WEB_PORT:-18080}"
DEV_MONGO="panic-dev-mongo"
mkdir -p "$OUT"
WORK="$(mktemp -d)"

cat > "$WORK/override.yaml" <<YAML
services:
  web:
    ports: !override ["127.0.0.1:${WEB_PORT}:8080"]
  server:
    environment:
      PANIC_ENV: prod
      PANIC_DJANGO_SECRET_KEY: loadtest-$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
      PANIC_MONGO_URI: mongodb://${DEV_MONGO}:27017/panic_loadtest
      PANIC_ALLOWED_HOSTS: 127.0.0.1,localhost
      PANIC_CSRF_TRUSTED_ORIGINS: http://127.0.0.1:${WEB_PORT}
      PANIC_SESSION_COOKIE_SECURE: "false"
      # web and the host-side Locust (via the bridge gateway) are the trusted test peers
      PANIC_TRUSTED_PROXY_CIDRS: ${SUBNET_PREFIX}.0/24
      PANIC_RATE_LIMIT_ENABLED: "false"
      PANIC_SEED_ON_START: never
      PANIC_GUNICORN_WORKERS: "2"
      PANIC_GUNICORN_THREADS: "8"
networks:
  default:
    ipam:
      config:
        - subnet: ${SUBNET_PREFIX}.0/24
YAML

compose() { PANIC_SERVER_REPLICAS=2 docker compose -p "$PROJECT" -f "$ROOT/Build/Containers/compose.yaml" -f "$WORK/override.yaml" "$@"; }
cleanup() {
    [[ -n "${STATS_PID:-}" ]] && kill "$STATS_PID" 2>/dev/null || true
    docker network disconnect "${PROJECT}_default" "$DEV_MONGO" >/dev/null 2>&1 || true
    compose down --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

cd "$ROOT"
uv sync --group dev --group loadtest >/dev/null
if [[ -z "${SKIP_BUILD:-}" ]]; then
    docker build -q -f Build/Containers/server/Containerfile -t panic-local/panic-server:latest . >/dev/null
    docker build -q -f Build/Containers/web/Containerfile -t panic-local/panic-web:latest . >/dev/null
fi
./panic start server >/dev/null 2>&1 || true   # ensures the dev MongoDB container is up
docker ps --format '{{.Names}}' | grep -qx "$DEV_MONGO" || { echo "$DEV_MONGO is not running" >&2; exit 1; }

echo "== stack up (1x web, 2x server) on the shared dev MongoDB, database panic_loadtest"
compose create >/dev/null 2>&1
docker network connect "${PROJECT}_default" "$DEV_MONGO" 2>/dev/null || true
compose up -d --wait --wait-timeout 180 >/dev/null

echo "== seed --profile loadtest (reset panic_loadtest) and mint sessions"
compose exec -T server python -m django panic_seed --profile loadtest --reset | tail -2
compose exec -T server python -m django shell < Build/LoadTest/mint_sessions.py | tail -1 > "$OUT/sessions.json"
python3 -c "import json,sys; n=len(json.load(open(sys.argv[1]))); assert n == $USERS, n; print(n, 'sessions')" "$OUT/sessions.json"

echo "== sampling container and Locust CPU every 5 s"
(
    echo "ts,name,cpu_percent,mem"
    while true; do
        docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' | grep "$PROJECT\|$DEV_MONGO" | sed "s/^/$(date +%s),/"
        lp=$(pgrep -f "locust -f" | head -1 || true)
        [[ -n "$lp" ]] && echo "$(date +%s),locust,$(ps -o %cpu= -p "$lp" | tr -d ' ')%,-"
        sleep 5
    done
) > "$OUT/cpu.csv" &
STATS_PID=$!

export PANIC_LT_SESSIONS="$OUT/sessions.json"
LOCUST=(.venv/bin/locust -f Build/LoadTest/locustfile.py --headless --host "http://127.0.0.1:${WEB_PORT}" --only-summary)

echo "== steady run: ${USERS} users, ${RAMP_S}s ramp, ${STEADY_S}s steady (stats reset after ramp)"
"${LOCUST[@]}" -u "$USERS" -r "$(python3 -c "print(round($USERS / $RAMP_S, 3))")" \
    -t "$((RAMP_S + STEADY_S))s" --reset-stats --csv "$OUT/steady" > "$OUT/steady.log" 2>&1 || true

echo "== stress run: ${USERS} users, no think time, ${STRESS_S}s"
PANIC_LT_NO_THINK=1 "${LOCUST[@]}" -u "$USERS" -r "$USERS" -t "${STRESS_S}s" --reset-stats \
    --csv "$OUT/stress" > "$OUT/stress.log" 2>&1 || true

echo "results: $OUT"

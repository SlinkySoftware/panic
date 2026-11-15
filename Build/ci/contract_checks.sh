#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Contract drift checks (T-S6-12): committed OpenAPI document and generated TS types match the code, the
# nginx template still generates from proxy-paths.json, and every compose file is valid.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== OpenAPI document matches the server"
./panic contracts --check

echo "== generated web API types match the OpenAPI document"
(cd Application/Web && npm run --silent gen:api:check)

echo "== nginx template generates from the allow-list"
python3 Build/scripts/gen_nginx_conf.py >/dev/null

echo "== compose files are valid"
tmp_env="$(mktemp)"; trap 'rm -f "$tmp_env"' EXIT
PANIC_SERVER_URL=http://panic-server:8210 docker compose -f Build/Containers/compose.yaml config -q
PANIC_SERVER_URL=http://panic-server:8210 docker compose -f Build/Containers/compose.standalone.web.yaml config -q
PANIC_MONGO_URI=mongodb://mongo/panic PANIC_ENV_FILE="$tmp_env" \
    docker compose -f Build/Containers/compose.standalone.server.yaml config -q
docker compose -f Build/Containers/compose.dev-mongo.yaml config -q
echo "contracts ok"

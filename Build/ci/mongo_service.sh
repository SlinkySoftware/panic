#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Start a throwaway mongo:8 for the Python tests and print `PANIC_TEST_MONGO_URI=...` (for $GITHUB_ENV).
#   mongo_service.sh start [port]   (default 27018)   |   mongo_service.sh stop
set -euo pipefail
NAME="panic-ci-mongo"
case "${1:-start}" in
    start)
        port="${2:-27018}"
        docker rm -f "$NAME" >/dev/null 2>&1 || true
        docker run -d --name "$NAME" -p "127.0.0.1:${port}:27017" docker.io/library/mongo:8 --quiet >/dev/null
        for _ in $(seq 1 60); do
            if docker exec "$NAME" mongosh --quiet --eval "db.runCommand('ping').ok" >/dev/null 2>&1; then
                echo "PANIC_TEST_MONGO_URI=mongodb://127.0.0.1:${port}/"
                exit 0
            fi
            sleep 1
        done
        docker logs "$NAME" >&2
        echo "mongo did not become ready" >&2
        exit 1
        ;;
    stop) docker rm -f "$NAME" >/dev/null 2>&1 || true ;;
    *) echo "usage: $0 start [port] | stop" >&2; exit 64 ;;
esac

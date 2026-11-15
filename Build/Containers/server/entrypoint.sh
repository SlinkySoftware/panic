#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# panic-server entrypoint: init (indexes, optional migrate / demo seed), then exec the command.
#   PANIC_MIGRATE_ON_START=true|false  (default true) run panic_migrate after panic_ensure_indexes
#   PANIC_SEED_ON_START=if-empty|never (default never in prod, if-empty otherwise: demo fixtures)
#   gunicorn tuning: PANIC_GUNICORN_WORKERS / _THREADS / _TIMEOUT (panic_server/gunicorn_conf.py)
set -eu
export DJANGO_SETTINGS_MODULE=panic_server.settings
. /usr/local/lib/panic/panic-env.sh

if [ "${1:-gunicorn}" = "gunicorn" ] || [ "${1:-}" = "init" ]; then
    python -m django panic_ensure_indexes
    if [ "${PANIC_MIGRATE_ON_START:-true}" = "true" ]; then
        python -m django panic_migrate
    fi
    if [ "${PANIC_ENV:-dev}" = "prod" ]; then default_seed=never; else default_seed=if-empty; fi
    case "${PANIC_SEED_ON_START:-$default_seed}" in
        if-empty) python -m django panic_seed --profile demo --if-empty ;;
        never) ;;
        *) echo "PANIC_SEED_ON_START must be if-empty|never" >&2; exit 64 ;;
    esac
fi

case "${1:-gunicorn}" in
    gunicorn) exec gunicorn -c python:panic_server.gunicorn_conf panic_server.wsgi:application ;;
    init) exit 0 ;;
    *) exec "$@" ;;
esac

#!/bin/sh
# PANIC Server container entrypoint: apply migrations, optionally seed, then exec the command.
#   PANIC_MIGRATE_ON_START=true|false  (default true)
#   PANIC_SEED_ON_START=if-empty|never (default if-empty)
#   PANIC_GUNICORN_WORKERS / PANIC_GUNICORN_THREADS / PANIC_GUNICORN_TIMEOUT
set -eu
export DJANGO_SETTINGS_MODULE=panic_server.settings

if [ "${PANIC_MIGRATE_ON_START:-true}" = "true" ]; then
    python -m django migrate --noinput
fi
case "${PANIC_SEED_ON_START:-if-empty}" in
    if-empty) python -m django panic_seed --if-empty ;;
    never) ;;
    *) echo "PANIC_SEED_ON_START must be if-empty|never" >&2; exit 64 ;;
esac

if [ "${1:-gunicorn}" = "gunicorn" ]; then
    exec gunicorn panic_server.wsgi:application \
        --bind "${PANIC_SERVER_BIND:-0.0.0.0:8210}" \
        --workers "${PANIC_GUNICORN_WORKERS:-2}" \
        --threads "${PANIC_GUNICORN_THREADS:-4}" \
        --timeout "${PANIC_GUNICORN_TIMEOUT:-30}" \
        --error-logfile - \
        --control-socket /tmp/gunicorn.ctl \
        --forwarded-allow-ips "${PANIC_GUNICORN_FORWARDED_ALLOW_IPS:-127.0.0.1}"
fi
exec "$@"

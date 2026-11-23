"""Gunicorn settings for the panic-server image: gthread workers, no preload.

``preload_app`` stays off so each worker opens its own MongoClient after the fork (pymongo clients are
not fork-safe).
"""

from __future__ import annotations

import os

bind = os.environ.get("PANIC_SERVER_BIND", "0.0.0.0:8210")
worker_class = "gthread"
workers = int(os.environ.get("PANIC_GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("PANIC_GUNICORN_THREADS", "8"))
timeout = int(os.environ.get("PANIC_GUNICORN_TIMEOUT", "30"))
graceful_timeout = 20
keepalive = 5
preload_app = False
# Client IPs are resolved by PANIC's own trusted-proxy chain (PANIC_TRUSTED_PROXY_CIDRS), not gunicorn.
forwarded_allow_ips = os.environ.get("PANIC_GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")
accesslog = None
errorlog = "-"
control_socket = "/tmp/gunicorn.ctl"  # noqa: S108 - private tmpfs inside the container

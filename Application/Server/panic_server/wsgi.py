"""WSGI config for PANIC Server."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "panic_server.settings")

application = get_wsgi_application()

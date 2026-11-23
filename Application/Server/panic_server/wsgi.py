"""WSGI config for PANIC Server (mounted under ``PANIC_BASE_PATH``, panic_server.paths)."""

from __future__ import annotations

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

from panic_server.paths import mount

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "panic_server.settings")

application = mount(get_wsgi_application(), settings.PANIC_BASE_PATH)

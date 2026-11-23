"""URL prefix (``PANIC_BASE_PATH``): PANIC served under a path such as ``/panic/`` on a shared host name.

panic-web forwards the full path, prefix included; :func:`mount` moves the prefix into ``SCRIPT_NAME``
so Django routes on the path below it (``request.path_info``) and ``request.path`` keeps the prefix.
Requests without the prefix (the container health check, ``/metrics``, direct calls on the server
port) are served as before. URLs the server hands to the browser go through :func:`app_path`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from django.core.exceptions import ImproperlyConfigured

#: One prefix segment. Letters, digits, ``-`` and ``_`` only: panic-web puts the prefix into nginx
#: locations (one of them a regex), so it must be free of nginx and regex syntax.
_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


def normalise_base_path(value: str | None) -> str:
    """``''`` for PANIC at ``/``, else ``/a`` or ``/a/b`` (``panic``, ``/panic`` and ``/panic/`` → ``/panic``)."""
    segments = [s for s in (value or "").split("/") if s]
    for s in segments:
        if not _SEGMENT.match(s):
            raise ImproperlyConfigured(
                f"PANIC_BASE_PATH: segment {s!r} may only contain letters, digits, '-' and '_' (got {value!r})"
            )
    return "".join(f"/{s}" for s in segments)


def app_path(path: str) -> str:
    """An absolute path inside this PANIC: ``app_path('/login')`` → ``/panic/login``."""
    from django.conf import settings

    return f"{settings.PANIC_BASE_PATH}{path if path.startswith('/') else '/' + path}"


WsgiApp = Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]


def mount(app: WsgiApp, base_path: str) -> WsgiApp:
    """Wrap ``app`` so a request under ``base_path`` has it moved from ``PATH_INFO`` to ``SCRIPT_NAME``."""
    if not base_path:
        return app

    def mounted(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        path = environ.get("PATH_INFO", "")
        if path == base_path or path.startswith(base_path + "/"):
            environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + base_path
            environ["PATH_INFO"] = path[len(base_path) :] or "/"
        return app(environ, start_response)

    return mounted

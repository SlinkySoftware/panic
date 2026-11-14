"""Lazily-created pymongo client (DATA_MODEL.md §2).

The client is created on first use so that importing Django settings never opens a
connection, and Gunicorn workers each create their own client on first use after fork
(``preload_app=False``). pymongo clients are thread-safe and fork-unsafe.

This module (and the rest of ``panic_server.store``) is the only place allowed to import
``pymongo`` / ``bson`` (AR-4.1).
"""

from __future__ import annotations

import threading
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import AutoReconnect, ConnectionFailure, NetworkTimeout, ServerSelectionTimeoutError

SERVER_SELECTION_TIMEOUT_MS = 3000
DEFAULT_DB_NAME = "panic"

_lock = threading.Lock()
_client: MongoClient[dict[str, Any]] | None = None


def _db_name_from_uri(uri: str) -> str:
    """Return the database name encoded in ``uri``'s path, or :data:`DEFAULT_DB_NAME`."""
    path = urlsplit(uri).path
    name = path.lstrip("/")
    return name or DEFAULT_DB_NAME


def get_client() -> MongoClient[dict[str, Any]]:
    """Return the per-process :class:`MongoClient`, creating it on first use."""
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                uri = settings.PANIC_MONGO_URI
                if not uri:
                    raise RuntimeError("PANIC_MONGO_URI is not configured")
                _client = MongoClient(
                    uri,
                    serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
                    tz_aware=True,
                    appname="panic-server",
                )
    return _client


def get_db(name: str | None = None) -> Database[dict[str, Any]]:
    """Return the configured database, or ``name`` when given (tests use a unique per-session db)."""
    if name:
        return get_client()[name]
    return get_client()[_db_name_from_uri(settings.PANIC_MONGO_URI)]


def reset_client() -> None:
    """Close and drop the per-process client. Used by tests to simulate a process restart."""
    global _client
    with _lock:
        if _client is not None:
            _client.close()
        _client = None


def ping(timeout_ms: int = 2000) -> tuple[bool, str | None]:
    """Return ``(True, None)`` if Mongo answers, else ``(False, <exception class name>)``."""
    try:
        client = get_client()
        client.admin.command("ping", maxTimeMS=timeout_ms)
    except Exception as e:
        return False, type(e).__name__
    return True, None


def is_transient(exc: BaseException) -> bool:
    """Return True if ``exc`` (or a cause in its chain) is a transient connectivity error."""
    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, AutoReconnect | ConnectionFailure | NetworkTimeout | ServerSelectionTimeoutError):
            return True
        e = e.__cause__ or e.__context__
    return False

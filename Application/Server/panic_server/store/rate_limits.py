"""``rate_limits`` repository (DATA_MODEL.md §4.12): fixed-window counters via an upserting ``$inc``.

Correctness relies on the window start being encoded in the document id, not on the TTL monitor
(which only sweeps roughly every 60s); the TTL index on ``expire_at`` just reclaims old windows.
Buckets: ``login:ip``, ``login:user``, ``api:ip``. Not wired into ``security.py``'s
``RateLimitMiddleware`` here (T-S6-04 owns that file); exercise this module directly.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pymongo.collection import ReturnDocument
from pymongo.database import Database

from panic_server.store.client import get_db

COLLECTION = "rate_limits"


def _window_start(now: dt.datetime, window_s: int) -> int:
    epoch = int(now.timestamp())
    return epoch - (epoch % window_s)


def increment(bucket: str, key: str, window_s: int, *, db: Database[dict[str, Any]] | None = None) -> int:
    """Increment the current fixed window for ``(bucket, key)`` and return the new count."""
    now = dt.datetime.now(dt.UTC)
    window_start = _window_start(now, window_s)
    doc_id = f"{bucket}:{key}:{window_start}"
    expire_at = dt.datetime.fromtimestamp(window_start + window_s, tz=dt.UTC)
    target_db = db if db is not None else get_db()
    doc = target_db[COLLECTION].find_one_and_update(
        {"_id": doc_id},
        {"$inc": {"count": 1}, "$setOnInsert": {"expire_at": expire_at}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    assert doc is not None  # upsert=True guarantees a document is returned
    return int(doc["count"])

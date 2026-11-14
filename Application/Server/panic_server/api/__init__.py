"""PANIC Server DRF API (``/api/v1/...``), built on top of ``panic_server.context``/``store`` (T-S6-06).

Every view here is a thin wrapper: request parsing and HTTP concerns only. Composition against
the store lives in ``panic_server.services`` (pure, store-repo-in / dict-out), so the service
layer stays unit-testable without an HTTP client (AR-4.1/6.x).
"""

from __future__ import annotations

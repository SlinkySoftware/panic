"""Domain exceptions raised at the ``panic_server.store`` boundary (AR-4.1).

Every repo write catches pymongo's own exceptions (``DuplicateKeyError``, ...) and re-raises
one of these instead, so no pymongo/bson type ever leaks past this package.
"""

from __future__ import annotations


class StoreError(Exception):
    """Base class for every domain exception raised by ``panic_server.store``."""


class NotFound(StoreError):
    """No document exists with the given ``_id`` (or matching the query)."""

    def __init__(self, collection: str, doc_id: str) -> None:
        self.collection = collection
        self.doc_id = doc_id
        super().__init__(f"{collection}: no document {doc_id!r}")


class VersionConflict(StoreError):
    """A CAS write's ``{_id, version: expected}`` filter matched no document (§3)."""

    def __init__(self, collection: str, doc_id: str, expected_version: int) -> None:
        self.collection = collection
        self.doc_id = doc_id
        self.expected_version = expected_version
        super().__init__(f"{collection}: version conflict on {doc_id!r} (expected version {expected_version})")


class DuplicateKey(StoreError):
    """A unique-index write collided (e.g. ``username``, ``code``, ``name``)."""

    def __init__(self, collection: str, detail: str = "") -> None:
        self.collection = collection
        self.detail = detail
        super().__init__(f"{collection}: duplicate key{f' ({detail})' if detail else ''}")

"""Shared CAS (compare-and-swap) write helpers used by every ``store.repos`` module (DATA_MODEL.md §3).

Every mutating write is ``find_one_and_update({_id, version: expected}, {...})``; no match means
either the document does not exist (:class:`~panic_server.store.errors.NotFound`) or someone else
wrote it first (:class:`~panic_server.store.errors.VersionConflict`). Unique-index violations on
insert or update become :class:`~panic_server.store.errors.DuplicateKey`. No pymongo exception or
type is ever raised past this module (AR-4.1).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from bson import ObjectId
from pymongo.collection import Collection, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.results import DeleteResult

from panic_server.store.errors import DuplicateKey, NotFound, VersionConflict


def utcnow() -> dt.datetime:
    """The BSON-date "now" used for every ``created_at``/``updated_at`` (DATA_MODEL.md §3)."""
    return dt.datetime.now(dt.UTC)


def new_id() -> str:
    """A fresh document id: UUIDv4 (DATA_MODEL.md §3)."""
    return str(uuid.uuid4())


def iso_z(value: dt.datetime) -> str:
    """Render a BSON date as an RFC 3339 ``...Z`` string, microseconds included when present.

    Keeping microsecond precision (when BSON stored it) matters for ``audit_log``'s keyset
    pagination, where several documents can share the same whole second (DATA_MODEL.md §4.9).
    """
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def from_iso_z(value: str) -> dt.datetime:
    """The inverse of :func:`iso_z`: parse an RFC 3339 ``...Z`` string back into a BSON date.

    Used by every repo's ``upsert_*`` primitive to translate an already-validated
    ``panic_common.models`` instance (e.g. from a portable export) back into Mongo's storage shape.
    """
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def base_kwargs(doc: dict[str, Any]) -> dict[str, Any]:
    """``_id`` -> ``id``, dates -> RFC 3339 strings, ``ObjectId`` -> ``str``; ready for a pydantic model.

    Extra keys not defined on the target model (e.g. ``password_hash``) are harmless: pydantic
    ignores unknown constructor kwargs by default, so they never reach the returned model.
    """
    out: dict[str, Any] = {}
    for k, v in doc.items():
        key = "id" if k == "_id" else k
        if isinstance(v, dt.datetime):
            v = iso_z(v)
        elif isinstance(v, ObjectId):
            v = str(v)
        out[key] = v
    return out


def insert_versioned(collection: Collection[dict[str, Any]], doc: dict[str, Any]) -> dict[str, Any]:
    """Insert a brand-new document (``version`` already set to 1 by the caller)."""
    try:
        collection.insert_one(doc)
    except DuplicateKeyError as e:
        raise DuplicateKey(collection.name, str(e)) from e
    return doc


def cas_update(
    collection: Collection[dict[str, Any]],
    doc_id: str,
    expected_version: int,
    update: dict[str, Any],
) -> dict[str, Any]:
    """``find_one_and_update({_id: doc_id, version: expected_version}, update)``, CAS-style.

    ``update`` must include ``{"$inc": {"version": 1}}`` (or similar); this helper does not add
    it, so callers can combine ``$set``/``$pull``/``$addToSet`` freely.
    """
    try:
        result = collection.find_one_and_update(
            {"_id": doc_id, "version": expected_version},
            update,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as e:
        raise DuplicateKey(collection.name, str(e)) from e
    if result is not None:
        return result
    if collection.find_one({"_id": doc_id}, {"_id": 1}) is None:
        raise NotFound(collection.name, doc_id)
    raise VersionConflict(collection.name, doc_id, expected_version)


def get_or_404(collection: Collection[dict[str, Any]], doc_id: str) -> dict[str, Any]:
    """Return the raw document with ``_id == doc_id``, or raise :class:`NotFound`."""
    doc = collection.find_one({"_id": doc_id})
    if doc is None:
        raise NotFound(collection.name, doc_id)
    return doc


def delete_versioned(collection: Collection[dict[str, Any]], doc_id: str, expected_version: int) -> None:
    """Delete a document, CAS-checked on ``version``; raise :class:`NotFound`/:class:`VersionConflict`."""
    result: DeleteResult = collection.delete_one({"_id": doc_id, "version": expected_version})
    if result.deleted_count == 1:
        return
    if collection.find_one({"_id": doc_id}, {"_id": 1}) is None:
        raise NotFound(collection.name, doc_id)
    raise VersionConflict(collection.name, doc_id, expected_version)

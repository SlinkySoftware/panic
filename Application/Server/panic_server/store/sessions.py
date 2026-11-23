"""Mongo-backed Django session store (DATA_MODEL.md §4.11, AR-4.7).

Reads ``ReadPreference.PRIMARY`` and writes ``w=majority``, overriding whatever the configured
``PANIC_MONGO_URI`` says, so a session created or updated through one panic-server
process/replica is read-your-write visible to another immediately -- a load balancer can move a
user between instances mid-session without a re-login. Configured as ``settings.SESSION_ENGINE``.
"""

from __future__ import annotations

from typing import Any

from django.contrib.sessions.backends.base import CreateError, SessionBase
from django.utils import timezone
from pymongo import ReadPreference, WriteConcern
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from panic_server.store.client import get_db

COLLECTION = "sessions"
#: The session-data key holding the signed-in user's id (DATA_MODEL.md §4.11); mirrored into the
#: document's ``uid`` field so :func:`delete_sessions_for_user` can ``delete_many`` on user disable.
_UID_SESSION_KEY = "panic_user_id"


def _collection(db_name: str | None = None) -> Collection[dict[str, Any]]:
    db = get_db(db_name)
    return db.get_collection(
        COLLECTION,
        read_preference=ReadPreference.PRIMARY,
        write_concern=WriteConcern(w="majority"),
    )


class SessionStore(SessionBase):
    """``django.contrib.sessions.backends.base.SessionBase`` backed by the ``sessions`` collection."""

    #: Test-only hook: a non-default database name (production always uses the configured one).
    db_name: str | None = None

    def _coll(self) -> Collection[dict[str, Any]]:
        return _collection(self.db_name)

    def load(self) -> dict[str, Any]:
        doc = self._coll().find_one({"_id": self.session_key, "expire_at": {"$gt": timezone.now()}})
        if doc is None:
            self._session_key = None
            return {}
        return self.decode(doc["data"])

    def exists(self, session_key: str) -> bool:
        return self._coll().count_documents({"_id": session_key}, limit=1) > 0

    def create(self) -> None:
        while True:
            self._session_key = self._get_new_session_key()
            try:
                self.save(must_create=True)
            except CreateError:
                continue
            self.modified = True
            return

    def save(self, must_create: bool = False) -> None:
        if self.session_key is None:
            self.create()
            return
        data = self._get_session(no_load=must_create)
        doc: dict[str, Any] = {
            "_id": self.session_key,
            "data": self.encode(data),
            "expire_at": self.get_expiry_date(),
        }
        uid = data.get(_UID_SESSION_KEY)
        if uid is not None:
            doc["uid"] = str(uid)
        coll = self._coll()
        if must_create:
            try:
                coll.insert_one(doc)
            except DuplicateKeyError as e:
                raise CreateError from e
        else:
            coll.replace_one({"_id": self.session_key}, doc, upsert=True)

    def delete(self, session_key: str | None = None) -> None:
        if session_key is None:
            if self.session_key is None:
                return
            session_key = self.session_key
        self._coll().delete_one({"_id": session_key})

    @classmethod
    def clear_expired(cls) -> None:
        """No-op: the TTL index on ``expire_at`` (DATA_MODEL.md §4.11) removes expired sessions."""
        return None


def delete_sessions_for_user(uid: str, *, db_name: str | None = None) -> int:
    """``delete_many({"uid": uid})`` -- called when a user is disabled."""
    result = _collection(db_name).delete_many({"uid": str(uid)})
    return result.deleted_count


__all__ = ["SessionStore", "delete_sessions_for_user"]

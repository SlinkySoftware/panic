"""CAS write helpers (``panic_server.store.cas``): NotFound / VersionConflict / DuplicateKey,
and the "exactly one winner" concurrency acceptance criterion."""

from __future__ import annotations

import threading

import pytest
from pymongo.database import Database

from panic_server.store.cas import cas_update, delete_versioned, get_or_404, insert_versioned, new_id, utcnow
from panic_server.store.errors import DuplicateKey, NotFound, VersionConflict

pytestmark = [pytest.mark.mongo]

COLLECTION = "_cas_fixture"


def test_insert_versioned_duplicate_key_raises_domain_error(mongo_db: Database) -> None:
    coll = mongo_db["_cas_fixture_dupe"]
    coll.create_index("code", unique=True, name="code_unique_cas_test")
    coll.insert_one({"_id": new_id(), "code": "DUPE", "version": 1})
    with pytest.raises(DuplicateKey):
        insert_versioned(coll, {"_id": new_id(), "code": "DUPE", "version": 1})


def test_cas_update_not_found(mongo_db: Database) -> None:
    coll = mongo_db[COLLECTION]
    with pytest.raises(NotFound):
        cas_update(coll, "does-not-exist", 1, {"$set": {"x": 1}, "$inc": {"version": 1}})


def test_cas_update_version_conflict(mongo_db: Database) -> None:
    coll = mongo_db[COLLECTION]
    doc_id = new_id()
    insert_versioned(coll, {"_id": doc_id, "n": 0, "version": 1})
    with pytest.raises(VersionConflict):
        cas_update(coll, doc_id, 99, {"$set": {"n": 1}, "$inc": {"version": 1}})


def test_cas_update_success_bumps_version(mongo_db: Database) -> None:
    coll = mongo_db[COLLECTION]
    doc_id = new_id()
    insert_versioned(coll, {"_id": doc_id, "n": 0, "version": 1})
    updated = cas_update(coll, doc_id, 1, {"$set": {"n": 1}, "$inc": {"version": 1}})
    assert updated["n"] == 1
    assert updated["version"] == 2


def test_delete_versioned_not_found_and_conflict(mongo_db: Database) -> None:
    coll = mongo_db[COLLECTION]
    with pytest.raises(NotFound):
        delete_versioned(coll, "nope", 1)
    doc_id = new_id()
    insert_versioned(coll, {"_id": doc_id, "version": 1})
    with pytest.raises(VersionConflict):
        delete_versioned(coll, doc_id, 5)
    delete_versioned(coll, doc_id, 1)
    with pytest.raises(NotFound):
        get_or_404(coll, doc_id)


def test_concurrent_cas_writes_yield_exactly_one_winner(mongo_db: Database) -> None:
    """Acceptance: N threads racing a CAS write from the same starting version -- one winner."""
    coll = mongo_db[COLLECTION]
    doc_id = new_id()
    insert_versioned(coll, {"_id": doc_id, "n": 0, "version": 1, "created_at": utcnow()})

    n_threads = 16
    results: list[str] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def attempt(worker: int) -> None:
        barrier.wait()
        try:
            cas_update(coll, doc_id, 1, {"$set": {"n": worker}, "$inc": {"version": 1}})
            outcome = "ok"
        except VersionConflict:
            outcome = "conflict"
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1
    assert results.count("conflict") == n_threads - 1

    final = get_or_404(coll, doc_id)
    assert final["version"] == 2

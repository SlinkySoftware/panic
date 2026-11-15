"""``manage.py panic_examples add|remove`` (``./panic addexamples`` / ``./panic delexamples``).

``add`` inserts the example dataset (``panic_server.fixtures.examples``: everything prefixed ``example-``,
``ex-`` usernames, ``EX-`` codes) next to existing data. Any example data already present (including an
older version of the dataset) is removed first, so re-running always gives the current set. If a code or
username the examples need is held by non-example data, nothing is written and the clashes are listed.
``remove`` deletes exactly the prefixed documents, then strips references real data picked up meanwhile
(example items in real lists, example widgets on real dashboards, example teams/zones on real resources,
example dashboards in real users' menus). Sites still used by real catalog items are kept and reported.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from panic_server.fixtures import examples
from panic_server.management.commands.panic_seed import _seed_fixture
from panic_server.store.cas import utcnow
from panic_server.store.client import get_db
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import orphans as orphans_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo
from panic_server.store.sessions import delete_sessions_for_user

PREFIX = {"$regex": f"^{examples.ID_PREFIX}"}
_BUMP = {"$inc": {"version": 1}}


class Command(BaseCommand):
    help = "Add or remove the example dataset without touching existing data."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["add", "remove"])

    def handle(self, *args: Any, **options: Any) -> None:
        db = get_db()
        if options["action"] == "add":
            fixture = examples.build()
            conflicts = _real_conflicts(db, fixture)
            if conflicts:
                raise CommandError(
                    "Not adding examples: these names are already used by non-example data: " + "; ".join(conflicts)
                )
            replaced = ""
            if any(db[c].count_documents({"_id": PREFIX}, limit=1) for c in _EXAMPLE_COLLECTIONS):
                replaced = " (previous example data replaced: " + _remove(db) + ")"
            created = _seed_fixture(db, fixture)
            zones_repo.invalidate_cache(db)
            summary = ", ".join(f"{k}={v}" for k, v in created.items())
            self.stdout.write(self.style.SUCCESS(f"examples added ({summary}){replaced}"))
            return
        self.stdout.write(self.style.SUCCESS("examples removed (" + _remove(db) + ")"))


_EXAMPLE_COLLECTIONS = (
    sites_repo.COLLECTION,
    teams_repo.COLLECTION,
    zones_repo.COLLECTION,
    users_repo.COLLECTION,
    catalog_repo.COLLECTION,
    lists_repo.COLLECTION,
    dashboards_repo.COLLECTION,
)


def _real_conflicts(db: Any, fixture: Any) -> list[str]:
    """Unique names (site/team codes, usernames) the examples need that non-example documents already hold."""
    found: list[str] = []
    for coll, field, values in (
        (sites_repo.COLLECTION, "code", [s.code for s in fixture.sites]),
        (teams_repo.COLLECTION, "code", [t.code for t in fixture.teams]),
        (users_repo.COLLECTION, "username", [u.username for u in fixture.users]),
    ):
        for doc in db[coll].find({field: {"$in": values}, "_id": {"$not": PREFIX}}, {field: 1}):
            found.append(f"{coll}.{field}={doc[field]}")
    return found


def _bump(extra: dict[str, Any]) -> dict[str, Any]:
    return {**extra, **_BUMP, "$set": {"updated_at": utcnow()}}


def _remove(db: Any) -> str:
    out: dict[str, int] = {}
    # 1. References from real data to example items / lists / dashboards.
    out["real lists cleaned"] = (
        db[lists_repo.COLLECTION]
        .update_many({"_id": {"$not": PREFIX}, "item_ids": PREFIX}, _bump({"$pull": {"item_ids": PREFIX}}))
        .modified_count
    )
    out["real dashboards cleaned"] = (
        db[dashboards_repo.COLLECTION]
        .update_many(
            {
                "_id": {"$not": PREFIX},
                "$or": [{"widgets.catalog_item_id": PREFIX}, {"widgets.list_id": PREFIX}],
            },
            _bump({"$pull": {"widgets": {"$or": [{"catalog_item_id": PREFIX}, {"list_id": PREFIX}]}}}),
        )
        .modified_count
    )
    users = db[users_repo.COLLECTION]
    users.update_many({"pinned_dashboard_ids": PREFIX}, {"$pull": {"pinned_dashboard_ids": PREFIX}})
    users.update_many({"default_dashboard_id": PREFIX}, {"$set": {"default_dashboard_id": None}})
    current = settings_repo.get_system_settings(db)
    if current and current.default_global_dashboard_id.startswith(examples.ID_PREFIX):
        settings_repo.set_default_global_dashboard(
            db, current.version, default_global_dashboard_id="", updated_by="cli:delexamples"
        )

    # 2. Example teams and zones, through the repos that $pull them from every resource and orphan
    #    real TEAM resources left with no team.
    for t in teams_repo.list_teams(db):
        if t.id.startswith(examples.ID_PREFIX):
            teams_repo.delete_team(db, t.id, t.version)
            out["teams"] = out.get("teams", 0) + 1
    for z in zones_repo.list_zones(db):
        if z.id.startswith(examples.ID_PREFIX):
            zones_repo.delete_zone(db, z.id, z.version)
            out["zones"] = out.get("zones", 0) + 1

    # 3. The example documents themselves.
    for name, coll in (
        ("catalog", catalog_repo.COLLECTION),
        ("lists", lists_repo.COLLECTION),
        ("dashboards", dashboards_repo.COLLECTION),
    ):
        out[name] = db[coll].delete_many({"_id": PREFIX}).deleted_count
    example_users = list(users.find({"_id": PREFIX}, {"_id": 1}))
    for u in example_users:
        delete_sessions_for_user(u["_id"])
    out["users"] = users.delete_many({"_id": PREFIX}).deleted_count
    if out["users"]:
        enabled = [u.username for u in users_repo.list_users(db, disabled=False)]
        orphans_repo.recompute_orphans_on_user_change(db, enabled)

    # 4. Sites last: keep any a real catalog item still uses.
    kept = []
    for s in sites_repo.list_sites(db):
        if not s.id.startswith(examples.ID_PREFIX):
            continue
        if db[catalog_repo.COLLECTION].count_documents({"site": s.code}, limit=1):
            kept.append(s.code)
            continue
        db[sites_repo.COLLECTION].delete_one({"_id": s.id})
        out["sites"] = out.get("sites", 0) + 1
    zones_repo.invalidate_cache(db)
    summary = ", ".join(f"{k}={v}" for k, v in out.items())
    return summary + (f"; kept sites still used by real items: {', '.join(kept)}" if kept else "")

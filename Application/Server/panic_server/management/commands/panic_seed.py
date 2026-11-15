"""``manage.py panic_seed`` -- idempotently seed canonical PANIC fixtures into MongoDB (T-S6-03).

Mongo-backed rewrite of the Stage 1-4 command: reaches Mongo only through
``panic_server.store``'s public API (AR-4.1), seeding one of the ``panic_server.fixtures``
profiles. Existing documents (matched by id) are never duplicated or overwritten; use
``--reset`` to force canonical values back.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from panic_common.search_keys import search_keys as compute_search_keys
from panic_server.fixtures import Fixture, build_profile
from panic_server.services.portability import wipe_all
from panic_server.store.client import get_db
from panic_server.store.errors import NotFound
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

#: ``section name -> (list-everything, get-by-id, upsert-by-id)``, mirroring ``services.portability``.
_REPOS: dict[str, tuple[Any, Any, Any]] = {
    "sites": (sites_repo.list_sites, sites_repo.get_site, sites_repo.upsert_site),
    "teams": (teams_repo.list_teams, teams_repo.get_team, teams_repo.upsert_team),
    "zones": (zones_repo.list_zones, zones_repo.get_zone, zones_repo.upsert_zone),
    "users": (users_repo.list_users, users_repo.get_user, users_repo.upsert_user),
    "catalog": (catalog_repo.list_all_catalog_items, catalog_repo.get_catalog_item, catalog_repo.upsert_catalog_item),
    "lists": (lists_repo.list_all_lists, lists_repo.get_list, lists_repo.upsert_list),
    "dashboards": (
        dashboards_repo.list_all_dashboards,
        dashboards_repo.get_dashboard,
        dashboards_repo.upsert_dashboard,
    ),
}

_FIXTURE_SECTIONS = ("sites", "teams", "zones", "users", "catalog", "lists", "dashboards")


def _profile_counts(db: Any) -> dict[str, int]:
    """Document counts for every profile-seeded section (the builtin Default zone excluded)."""
    counts: dict[str, int] = {}
    for section in _FIXTURE_SECTIONS:
        list_all, _get, _upsert = _REPOS[section]
        if section == "zones":
            counts[section] = len([z for z in list_all(db) if z.id != zones_repo.DEFAULT_ZONE_ID])
        else:
            counts[section] = len(list_all(db))
    return counts


def _fixture_objects(fixture: Fixture, section: str) -> list[Any]:
    by_section: dict[str, list[Any]] = {
        "sites": fixture.sites,
        "teams": fixture.teams,
        "zones": fixture.zones,
        "users": fixture.users,
        "catalog": fixture.catalog,
        "lists": fixture.lists,
        "dashboards": fixture.dashboards,
    }
    return by_section[section]


def with_search_keys(section: str, obj: Any) -> Any:
    """Fixtures are plain models: fill in ``search_keys`` the way the services do on create, or seeded
    data is invisible to palette and catalog search."""
    if getattr(obj, "search_keys", None) or not hasattr(obj, "search_keys"):
        return obj
    if section == "catalog":
        keys = compute_search_keys(obj.title, obj.host, obj.site, obj.tags)
    elif section == "users":
        keys = compute_search_keys(obj.display_name, "", "", [], obj.username)
    elif section in ("lists", "dashboards"):
        keys = compute_search_keys(obj.title, "", "", [])
    else:
        return obj
    return obj.model_copy(update={"search_keys": keys})


def _seed_fixture(db: Any, fixture: Fixture) -> dict[str, int]:
    """Insert every document in ``fixture`` whose id does not already exist. Never overwrites."""
    created: dict[str, int] = {}
    for section in _FIXTURE_SECTIONS:
        _list_all, get_one, upsert = _REPOS[section]
        n = 0
        for obj in _fixture_objects(fixture, section):
            try:
                get_one(db, obj.id)
            except NotFound:
                upsert(db, with_search_keys(section, obj))
                n += 1
        created[section] = n
    if fixture.system_settings is not None and settings_repo.get_system_settings(db) is None:
        settings_repo.upsert_system_settings(db, fixture.system_settings)
    return created


class Command(BaseCommand):
    help = (
        "Seed canonical sites, teams, zones, users, catalog items, lists, dashboards and system settings "
        "into MongoDB. Idempotent: existing records are never duplicated or overwritten."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--profile", required=True, choices=["demo", "loadtest"], help="Seed profile to load.")
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--reset", action="store_true", help="Wipe ALL portal data, then re-seed (destructive).")
        group.add_argument("--if-empty", action="store_true", help="Only seed when the database has no data.")

    def handle(self, *args: Any, **options: Any) -> None:
        db = get_db()

        if options["reset"]:
            wipe_all(db)
        else:
            zones_repo.ensure_default_zone(db)
            settings_repo.ensure_system_settings(db, default_global_dashboard_id="", updated_by="system")

        if options["if_empty"] and sum(_profile_counts(db).values()) > 0:
            self.stdout.write("panic_seed: database already contains data; skipping (--if-empty).")
            return

        fixture = build_profile(options["profile"])
        created = _seed_fixture(db, fixture)
        summary = ", ".join(f"{k}={v}" for k, v in created.items())
        verb = "reset and seeded" if options["reset"] else "seeded"
        self.stdout.write(self.style.SUCCESS(f"panic_seed: {verb} profile={options['profile']!r} ({summary})"))

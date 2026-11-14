"""``manage.py panic_seed`` — idempotently seed canonical PANIC fixtures into the relational database."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from panic_server.store_db import DatabasePortalStore


class Command(BaseCommand):
    help = (
        "Seed canonical sites, teams, zones, users, catalog items, lists, dashboards and system settings. "
        "Idempotent: existing records are never duplicated or overwritten."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--reset", action="store_true", help="Wipe ALL portal data, then re-seed (destructive).")
        group.add_argument("--if-empty", action="store_true", help="Only seed when the database has no data.")

    def handle(self, *args: Any, **options: Any) -> None:
        store = DatabasePortalStore()
        if options["if_empty"] and not store.is_empty():
            self.stdout.write("panic_seed: database already contains data; skipping (--if-empty).")
            return
        created = store.seed_defaults(force=bool(options["reset"]))
        summary = ", ".join(f"{k}={v}" for k, v in created.items())
        verb = "reset and seeded" if options["reset"] else "seeded"
        self.stdout.write(self.style.SUCCESS(f"panic_seed: {verb} ({summary})"))

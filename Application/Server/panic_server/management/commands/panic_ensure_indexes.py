"""``manage.py panic_ensure_indexes``: create the PANIC Mongo database's indexes. Idempotent."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from panic_server.store.client import get_db
from panic_server.store.indexes import ensure_indexes


class Command(BaseCommand):
    help = "Create missing indexes in the PANIC database (DATA_MODEL.md §4). Safe to run repeatedly."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            report = ensure_indexes(get_db())
        except RuntimeError as e:
            raise CommandError(str(e)) from e
        for name in report.dropped:
            self.stdout.write(f"dropped obsolete {name}")
        for name in report.changed:
            self.stdout.write(f"changed {name}")
        for name in report.created:
            self.stdout.write(f"created {name}")
        self.stdout.write(
            self.style.SUCCESS(
                f"indexes: {len(report.created)} created, {len(report.existing)} already present, "
                f"{len(report.changed)} changed, {len(report.dropped)} dropped"
            )
        )

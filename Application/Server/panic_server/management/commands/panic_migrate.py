"""``manage.py panic_migrate``: run idempotent data migrations against the PANIC database
(DATA_MODEL.md §4.13). The migration logic lives in ``panic_server.store.migrate`` (AR-4.1);
this command is a thin CLI wrapper.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from panic_server.store.client import get_db
from panic_server.store.migrate import run_migrations


class Command(BaseCommand):
    help = "Run idempotent data migrations against the PANIC database. Safe to run repeatedly."

    def handle(self, *args: Any, **options: Any) -> None:
        applied = run_migrations(get_db())
        if not applied:
            self.stdout.write("panic_migrate: already up to date.")
            return
        for line in applied:
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS(f"panic_migrate: applied {len(applied)} step(s)."))

"""``manage.py panic_import`` -- load a ``panic-export`` (schema_version 2) JSON document into
MongoDB. Entities are upserted by id."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from panic_server.services.portability import ImportValidationError, import_state
from panic_server.store.client import get_db


class Command(BaseCommand):
    help = "Import a panic-export (schema_version 2) JSON document. Entities are upserted by id."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("input", help="Input file ('-' for stdin).")
        parser.add_argument("--replace", action="store_true", help="Wipe ALL portal data first (destructive).")

    def handle(self, *args: Any, **options: Any) -> None:
        raw = sys.stdin.read() if options["input"] == "-" else Path(options["input"]).read_text(encoding="utf-8")
        try:
            counts = import_state(get_db(), json.loads(raw), replace=bool(options["replace"]))
        except (ValueError, ImportValidationError) as e:
            raise CommandError(f"panic_import: {e}") from e
        summary = ", ".join(f"{k}={v}" for k, v in counts.items())
        self.stdout.write(self.style.SUCCESS(f"panic_import: imported ({summary})"))

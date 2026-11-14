"""``manage.py panic_export`` — write portal state as a portable JSON document."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from panic_server.portability import export_state
from panic_server.store_db import DatabasePortalStore


class Command(BaseCommand):
    help = "Export sites, teams, zones, users, catalog items, lists, dashboards and settings as JSON."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--output", "-o", default="-", help="Output file (default: stdout).")
        parser.add_argument(
            "--shared-only", action="store_true", help="Omit users and PERSONAL-scoped items, lists and dashboards."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        doc = export_state(DatabasePortalStore(), shared_only=bool(options["shared_only"]))
        text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        if options["output"] == "-":
            sys.stdout.write(text)
        else:
            Path(options["output"]).write_text(text, encoding="utf-8")
            self.stderr.write(f"panic_export: wrote {options['output']}")

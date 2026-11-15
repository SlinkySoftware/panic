"""``manage.py panic_user_admin promote|demote <username>``: grant or remove ``GLOBAL_ADMIN`` from the shell.

For operators with shell access (e.g. the first LDAP/OIDC admin before anyone can use /settings/users).
Goes through ``admin_service.update_user``, so the last enabled Global Admin cannot be demoted. Audited
with actor ``cli:<os user>``.
"""

from __future__ import annotations

import getpass
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from panic_common.models import PermissionFlag
from panic_server.api.errors import ApiError
from panic_server.services import admin as admin_service
from panic_server.store.client import get_db
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import users as users_repo


class Command(BaseCommand):
    help = "Grant (promote) or remove (demote) the Global Admin permission for an existing user."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("action", choices=["promote", "demote"])
        parser.add_argument("username")

    def handle(self, *args: Any, **options: Any) -> None:
        db = get_db()
        username: str = options["username"]
        user = users_repo.get_user_by_username(db, username)
        if user is None:
            raise CommandError(
                f"No PANIC user {username!r}. Users are created on their first sign-in (or on /settings/users)."
            )
        admin = str(PermissionFlag.GLOBAL_ADMIN)
        perms = {str(p) for p in user.permissions}
        if options["action"] == "promote":
            if admin in perms:
                self.stdout.write(f"{username} is already a Global Admin.")
                return
            perms.add(admin)
        else:
            if admin not in perms:
                self.stdout.write(f"{username} is not a Global Admin.")
                return
            perms.discard(admin)
        try:
            admin_service.update_user(db, user.id, user.version, permissions=sorted(perms))
        except ApiError as e:
            raise CommandError(str(e)) from e
        audit_repo.append_audit(
            db,
            actor_username=f"cli:{getpass.getuser()}",
            action=f"admin.user.{options['action']}",
            target_type="user_account",
            target_id=user.id,
            summary=f"{'Granted' if options['action'] == 'promote' else 'Removed'} Global Admin for {username} (CLI)",
            client_ip="127.0.0.1",
        )
        verb = "is now" if options["action"] == "promote" else "is no longer"
        self.stdout.write(self.style.SUCCESS(f"{username} {verb} a Global Admin."))

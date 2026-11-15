"""``./panic promote|demote <username>`` (manage.py panic_user_admin): grants / removes GLOBAL_ADMIN via
the admin service, audits it, and refuses to demote the last enabled Global Admin."""

from __future__ import annotations

import uuid
from typing import Any
from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import users as users_repo


def _user(db: Any, perms: list[str] | None = None) -> Any:
    name = f"cli-{uuid.uuid4().hex[:8]}"
    return users_repo.create_user(
        db, username=name, display_name=name, default_remote_user=name, auth_source="LDAP", permissions=perms or []
    )


def test_promote_then_demote(mongo_db: Any) -> None:
    u = _user(mongo_db)
    call_command("panic_user_admin", "promote", u.username)
    assert "GLOBAL_ADMIN" in {str(p) for p in users_repo.get_user(mongo_db, u.id).permissions}
    call_command("panic_user_admin", "demote", u.username)
    assert "GLOBAL_ADMIN" not in {str(p) for p in users_repo.get_user(mongo_db, u.id).permissions}
    actions = [e.action for e in audit_repo.list_audit(mongo_db, limit=50, target_id=u.id)]
    assert "admin.user.promote" in actions and "admin.user.demote" in actions


def test_unknown_user_and_last_admin_are_refused(mongo_db: Any) -> None:
    with pytest.raises(CommandError, match="No PANIC user"):
        call_command("panic_user_admin", "promote", "no-such-user-xyz")
    u = _user(mongo_db, ["GLOBAL_ADMIN"])
    with mock.patch.object(users_repo, "count_enabled_admins", return_value=1), pytest.raises(CommandError):
        call_command("panic_user_admin", "demote", u.username)
    assert "GLOBAL_ADMIN" in {str(p) for p in users_repo.get_user(mongo_db, u.id).permissions}

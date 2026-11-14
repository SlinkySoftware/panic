"""``/api/v1/me`` composition and writes (API.md §4.4). Writes always act on the **real** signed-in
user (``context.real_user``); the view layer refuses them outright during View As
(``services.view_as.assert_not_view_as``) before any of these functions ever run.
"""

from __future__ import annotations

import re
from typing import Any

from panic_common.errors import ErrorCode
from panic_common.hygiene import check_credential_hygiene
from panic_common.models import Protocol, UserAccount
from panic_common.visibility import matches, visibility_spec
from panic_server.api.errors import ApiError
from panic_server.store.errors import NotFound
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import settings as settings_repo
from panic_server.store.repos import users as users_repo

#: API.md §4.4: "hygiene rules on ssh_template/default_remote_user (no spaces, colons, password
#: flags)" -- a narrower rule than catalog items' full ``check_credential_hygiene`` (which looks
#: for ``user:pass@host`` and private-key material, neither relevant here), so the "no spaces,
#: colons" half is checked directly and the "password flags" half reuses the shared regex-backed
#: checker by feeding the template through its ``path_or_args`` slot (my call: documented here,
#: not a widening of ``panic_common.hygiene`` itself).
_REMOTE_USER_INVALID_RE = re.compile(r"[\s:]")
_EDITABLE_FIELDS = frozenset(
    {"display_name", "default_remote_user", "ssh_template", "density", "theme", "unreachable_policy"}
)


def build_me(user: UserAccount) -> dict[str, Any]:
    """``GET /api/v1/me``'s shape (API.md §4.4) -- distinct from ``build_profile``'s bootstrap shape."""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "default_remote_user": user.default_remote_user,
        "ssh_template": user.ssh_template,
        "prefs": {
            "density": str(user.density),
            "theme": str(user.theme),
            "unreachable_policy": str(user.unreachable_policy),
        },
        "default_dashboard_id": user.default_dashboard_id,
        "pinned_dashboard_ids": list(user.pinned_dashboard_ids),
        "version": user.version,
    }


def _hygiene_errors(ssh_template: str | None, default_remote_user: str | None) -> list[str]:
    errors: list[str] = []
    if default_remote_user is not None:
        if _REMOTE_USER_INVALID_RE.search(default_remote_user):
            errors.append("default_remote_user may not contain spaces or colons.")
        errors.extend(check_credential_hygiene(Protocol.SSH, host=default_remote_user))
    if ssh_template is not None:
        errors.extend(check_credential_hygiene(Protocol.SSH, host="", path_or_args=ssh_template))
    return errors


def update_me(db: Any, real_user: UserAccount, expected_version: int, **fields: Any) -> UserAccount:
    """``PATCH /api/v1/me``: any editable field except pins/default dashboard (their own endpoints)."""
    unknown = set(fields) - _EDITABLE_FIELDS
    if unknown:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, f"Unknown or read-only field(s): {', '.join(sorted(unknown))}.", status_code=400
        )
    errors = _hygiene_errors(fields.get("ssh_template"), fields.get("default_remote_user"))
    if errors:
        raise ApiError(
            ErrorCode.CREDENTIAL_HYGIENE_VIOLATION,
            "Credential hygiene violation.",
            status_code=400,
            hygiene_errors=errors,
        )
    return users_repo.update_user(db, real_user.id, expected_version, **fields)


def _visible_dashboard_or_404(db: Any, real_user: UserAccount, dashboard_id: str) -> Any:
    try:
        dashboard = dashboards_repo.get_dashboard(db, dashboard_id)
    except NotFound:
        raise ApiError(ErrorCode.NOT_FOUND, "Dashboard not found.", status_code=404) from None
    if not matches(visibility_spec(real_user), dashboard):
        raise ApiError(ErrorCode.NOT_FOUND, "Dashboard not found.", status_code=404)
    return dashboard


def set_default_dashboard(
    db: Any, real_user: UserAccount, expected_version: int, dashboard_id: str | None
) -> UserAccount:
    """``PUT /api/v1/me/default-dashboard``: must be visible; also pins it."""
    pinned = list(real_user.pinned_dashboard_ids)
    if dashboard_id is not None:
        _visible_dashboard_or_404(db, real_user, dashboard_id)
        if dashboard_id not in pinned:
            pinned.append(dashboard_id)
    return users_repo.update_user(
        db, real_user.id, expected_version, default_dashboard_id=dashboard_id, pinned_dashboard_ids=pinned
    )


def pin_dashboard(db: Any, real_user: UserAccount, expected_version: int, dashboard_id: str) -> UserAccount:
    """``PUT /api/v1/me/menu/{dashboard_id}``: pin (must be visible GLOBAL/TEAM, or own PERSONAL)."""
    _visible_dashboard_or_404(db, real_user, dashboard_id)
    pinned = list(real_user.pinned_dashboard_ids)
    if dashboard_id not in pinned:
        pinned.append(dashboard_id)
    return users_repo.update_user(db, real_user.id, expected_version, pinned_dashboard_ids=pinned)


def unpin_dashboard(db: Any, real_user: UserAccount, expected_version: int, dashboard_id: str) -> UserAccount:
    """``DELETE /api/v1/me/menu/{dashboard_id}``: unpin, or ``409 PROTECTED_RESOURCE`` for an
    ``always_display``/app-wide-default dashboard or the user's last remaining pin."""
    pinned = list(real_user.pinned_dashboard_ids)
    if dashboard_id not in pinned:
        return real_user  # idempotent: nothing to unpin.

    try:
        dashboard = dashboards_repo.get_dashboard(db, dashboard_id)
    except NotFound:
        dashboard = None

    settings_doc = settings_repo.get_system_settings(db)
    is_global_default = bool(settings_doc and settings_doc.default_global_dashboard_id == dashboard_id)
    if (dashboard is not None and dashboard.always_display) or is_global_default:
        raise ApiError(ErrorCode.PROTECTED_RESOURCE, "This dashboard cannot be removed from the menu.", status_code=409)
    if len(pinned) <= 1:
        raise ApiError(ErrorCode.PROTECTED_RESOURCE, "At least one dashboard must remain pinned.", status_code=409)

    pinned.remove(dashboard_id)
    return users_repo.update_user(db, real_user.id, expected_version, pinned_dashboard_ids=pinned)


__all__ = ["build_me", "pin_dashboard", "set_default_dashboard", "unpin_dashboard", "update_me"]

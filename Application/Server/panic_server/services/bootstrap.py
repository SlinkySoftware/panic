"""``GET /api/v1/ui/bootstrap`` composition (API.md §4.2).

``build_profile`` (the ``me``/``real_user`` shape) is shared verbatim with ``POST
/api/v1/auth/login``'s ``{"me": ...}`` response (API.md §4.1 says to reuse it, not duplicate it).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings as django_settings

from panic_common.models import Dashboard, PermissionFlag, UserAccount
from panic_common.rbac import can_use_view_as, has_permission
from panic_common.visibility import DEFAULT_ZONE_ID, visibility_spec
from panic_server import __version__
from panic_server.auth.roles import sees_super_admin
from panic_server.context import RequestContext
from panic_server.store.repos import dashboards as dashboards_repo
from panic_server.store.repos import settings as settings_repo


def build_profile(user: UserAccount) -> dict[str, Any]:
    """The ``me``/``real_user``/``view_as`` subject shape, shared by bootstrap and login."""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "auth_source": str(user.auth_source),
        "prefs": {
            "density": str(user.density),
            "theme": str(user.theme),
            "unreachable_policy": str(user.unreachable_policy),
        },
    }


def _subject(user: UserAccount) -> dict[str, Any]:
    """The smaller ``{id, username, display_name}`` shape used for the View As subject."""
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


def _resolve_default_dashboard(
    user: UserAccount, visible_by_id: dict[str, Dashboard], default_global_dashboard_id: str | None
) -> dict[str, Any] | None:
    """The three-step precedence (DATA_MODEL.md §4.7)."""
    if user.default_dashboard_id and user.default_dashboard_id in visible_by_id:
        return {"id": user.default_dashboard_id, "source": "USER"}
    if default_global_dashboard_id and default_global_dashboard_id in visible_by_id:
        return {"id": default_global_dashboard_id, "source": "SYSTEM_GLOBAL"}
    if visible_by_id:
        fallback = min(visible_by_id.values(), key=lambda d: (d.sort_order, d.id))
        return {"id": fallback.id, "source": "FALLBACK"}
    return None


def _nav_dashboards(
    user: UserAccount,
    visible_dashboards: list[Dashboard],
    default_id: str | None,
    max_count: int,
) -> list[Dashboard]:
    """Navigation menu rule (DATA_MODEL.md §4.7): always_display/default/pinned, else everything."""
    pins = set(user.pinned_dashboard_ids)
    if pins:
        selected = [d for d in visible_dashboards if d.always_display or d.id == default_id or d.id in pins]
    else:
        selected = list(visible_dashboards)
    return selected[:max_count]


def build_bootstrap(db: Any, context: RequestContext) -> dict[str, Any]:
    """Build the whole ``/ui/bootstrap`` payload for ``context`` (A: ``effective_user`` is set)."""
    effective = context.effective_user
    real = context.real_user

    me = build_profile(effective) if effective is not None else None
    real_profile = build_profile(real) if (real is not None and context.view_as_active) else None
    view_as = _subject(effective) if (context.view_as_active and effective is not None) else None

    permissions = {
        "global_admin": bool(effective and has_permission(effective, PermissionFlag.GLOBAL_ADMIN)),
        "can_add_global": bool(effective and has_permission(effective, PermissionFlag.CAN_ADD_GLOBAL)),
        "can_add_team": bool(effective and has_permission(effective, PermissionFlag.CAN_ADD_TEAM)),
        # Only a *real* admin may start View As (AR-2.9); this is deliberately checked on
        # ``real``, not ``effective``, unlike the three permissions above.
        "can_view_as": bool(real and can_use_view_as(real)),
        # Application settings and config export/import; never true while viewing as a non-super admin.
        "super_admin": sees_super_admin(real, effective),
    }

    zone = context.zone
    zone_matched_cidr = context.chain.location_known and zone is not None and zone.id != DEFAULT_ZONE_ID
    zone_source = "VIEW_AS" if context.view_as_zone else "CIDR" if zone_matched_cidr else "DEFAULT"
    client = {
        "ip": context.client_ip,
        "zone": {"id": zone.id, "name": zone.name} if zone is not None else None,
        "zone_source": zone_source,
    }

    nav: list[dict[str, Any]] = []
    default_dashboard: dict[str, Any] | None = None
    if effective is not None:
        spec = visibility_spec(effective)
        visible_dashboards = dashboards_repo.list_visible_dashboards(db, spec)
        visible_by_id = {d.id: d for d in visible_dashboards}
        settings_doc = settings_repo.get_system_settings(db)
        default_global_id = settings_doc.default_global_dashboard_id if settings_doc else None
        default_dashboard = _resolve_default_dashboard(effective, visible_by_id, default_global_id)
        default_id = default_dashboard["id"] if default_dashboard else None
        for d in _nav_dashboards(effective, visible_dashboards, default_id, django_settings.PANIC_NAV_MAX_DASHBOARDS):
            nav.append(
                {
                    "id": d.id,
                    "title": d.title,
                    "icon": d.icon,
                    "default": d.id == default_id,
                    "locked": d.always_display or d.id == default_id,
                }
            )

    return {
        "instance": {"name": django_settings.PANIC_INSTANCE_NAME, "version": __version__},
        "me": me,
        "real_user": real_profile,
        "view_as": view_as,
        "permissions": permissions,
        "client": client,
        "nav": {"dashboards": nav},
        "default_dashboard": default_dashboard,
    }


__all__ = ["build_bootstrap", "build_profile"]

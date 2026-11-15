"""View As: the read-only-mutation guard, and starting/exiting a View As session (API.md §4.7,
AR-2.9). Owned by T-S6-07; the session key and ``RequestContext`` plumbing are T-S6-04's.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from panic_common.errors import ErrorCode
from panic_server.api.errors import ApiError
from panic_server.context import SESSION_VIEW_AS_KEY, SESSION_VIEW_AS_ZONE_KEY, RequestContext, build_request_context
from panic_server.services.audit import record_audit
from panic_server.services.bootstrap import build_bootstrap
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

_READ_ONLY_DETAIL = "This action is not allowed while View As is active. Exit View As first."


def assert_not_view_as(context: RequestContext) -> None:
    """Refuse a mutation while View As is active (API.md §3 ``VIEW_AS_READ_ONLY``).

    Every mutation everywhere must call this except ``DELETE /api/v1/admin/view-as`` itself (the
    one explicit exception, API.md §4.7) -- that view never calls it.
    """
    if context.view_as_active:
        raise ApiError(ErrorCode.VIEW_AS_READ_ONLY, _READ_ONLY_DETAIL, status_code=403)


def start_view_as(
    db: Any, django_request: HttpRequest, target_user_id: str | None, zone_id: str | None = None
) -> dict[str, Any]:
    """``PUT /api/v1/admin/view-as``: a real admin views as a user, a zone, or both.

    ``target_user_id`` empty = the admin themselves; ``zone_id`` empty = the real client zone. At least
    one must be given. Returns the fresh bootstrap payload for the new perspective. Raises
    :class:`~panic_server.store.errors.NotFound` for an unknown user or zone (404) and ``ApiError`` (400)
    for a disabled user or an empty request.
    """
    if not target_user_id and not zone_id:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "Choose a user, a zone, or both.", status_code=400)
    real = django_request.context.real_user
    assert real is not None  # IsRealGlobalAdmin already guarantees this
    target = users_repo.get_user(db, target_user_id) if target_user_id else None
    if target is not None and target.disabled:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "Cannot View As a disabled user.", status_code=400)
    zone = zones_repo.get_zone(db, zone_id) if zone_id else None
    session = django_request.session
    if target is not None and target.id != real.id:
        session[SESSION_VIEW_AS_KEY] = target.id
    else:
        session.pop(SESSION_VIEW_AS_KEY, None)
    if zone is not None:
        session[SESSION_VIEW_AS_ZONE_KEY] = zone.id
    else:
        session.pop(SESSION_VIEW_AS_ZONE_KEY, None)
    new_context = build_request_context(django_request)
    django_request.context = new_context
    who = target.username if target is not None else real.username
    where = f" in zone {zone.name}" if zone is not None else ""
    record_audit(
        db,
        django_request,
        action="admin.view_as.start",
        target_type="user_account",
        target_id=target.id if target is not None else real.id,
        summary=f"{real.username} started View As {who}{where}",
        details={"zone_id": zone.id} if zone is not None else None,
    )
    return build_bootstrap(db, new_context)


def exit_view_as(db: Any, django_request: HttpRequest) -> dict[str, Any]:
    """``DELETE /api/v1/admin/view-as``: leave View As. The only mutation allowed while it is
    active (API.md §4.7) -- this view never calls :func:`assert_not_view_as`."""
    context: RequestContext = django_request.context
    real = context.real_user
    assert real is not None  # IsRealGlobalAdmin already guarantees this
    subject_username = context.effective_user.username if context.effective_user is not None else None

    django_request.session.pop(SESSION_VIEW_AS_KEY, None)
    django_request.session.pop(SESSION_VIEW_AS_ZONE_KEY, None)
    new_context = build_request_context(django_request)
    django_request.context = new_context

    record_audit(
        db,
        django_request,
        action="admin.view_as.exit",
        target_type="user_account",
        target_id=real.id,
        summary=(
            f"{real.username} exited View As {subject_username}"
            if subject_username
            else f"{real.username} exited View As"
        ),
    )
    return build_bootstrap(db, new_context)


__all__ = ["assert_not_view_as", "exit_view_as", "start_view_as"]

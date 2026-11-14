"""Shared audit-write helper (T-S6-07) used by every mutation view under ``panic_server.api``.

Every successful create/update/delete writes one entry via ``store.repos.audit.append_audit``,
recording the **real** actor (never the View As target), the View As subject when active, the
caller's client IP/zone and the request id (T-S6-04's ``RequestIdMiddleware``). Centralising this
here means no view re-derives that plumbing by hand.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from panic_server.store.repos import audit as audit_repo


def record_audit(
    db: Any,
    django_request: HttpRequest,
    *,
    action: str,
    target_type: str,
    target_id: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one audit entry for ``django_request``'s caller (API.md §3 audit fields).

    ``django_request`` must already carry ``.context`` (``RequestContextMiddleware``, T-S6-04)
    and, when a client sent one, ``.request_id`` (``RequestIdMiddleware``). Safe to call even for
    an anonymous-looking context (falls back to ``"anonymous"``), though in practice every caller
    of this helper is behind an ``IsAuthenticated``/``IsGlobalAdmin`` view.
    """
    context = django_request.context
    real = context.real_user
    effective = context.effective_user
    if real is not None:
        actor_username = real.username
    elif effective is not None:
        actor_username = effective.username
    else:
        actor_username = "anonymous"
    view_as_username = effective.username if (context.view_as_active and effective is not None) else None

    audit_repo.append_audit(
        db,
        actor_username=actor_username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        client_ip=context.client_ip,
        details=details,
        view_as_username=view_as_username,
        zone_id=context.zone.id if context.zone is not None else None,
        request_id=getattr(django_request, "request_id", None),
    )


__all__ = ["record_audit"]

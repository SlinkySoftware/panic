"""Per-request, lock-free request context.

A plain value resolved fresh for every request from that request's own session and headers. There is no
process-level cache, global, or lock here (ADR-0001 decision 6): a :class:`RequestContext` is
built once per request by ``panic_server.middleware.RequestContextMiddleware`` and stashed as
``request.context``. Because every field is read from the ``request`` object passed in, and
``request`` objects are never shared between concurrent requests (Django's WSGI/sync workers
handle one request per thread at a time), two concurrent requests from different users in the
same worker can never see each other's resolved identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.http import HttpRequest

from panic_common.models import SecurityZone, UserAccount
from panic_common.proxy import ChainResolution, ProxyChainConfig, resolve_client_chain
from panic_common.rbac import can_use_view_as
from panic_common.zones import resolve_ip_zone
from panic_server.store.client import get_db
from panic_server.store.errors import NotFound
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

#: Session key holding the signed-in user's id (mirrored into ``sessions.uid`` by the store).
SESSION_USER_KEY = "panic_user_id"
#: Session key holding the admin's current View As target, when active (AR-2.9).
SESSION_VIEW_AS_KEY = "panic_view_as_user_id"
SESSION_VIEW_AS_ZONE_KEY = "panic_view_as_zone_id"

#: Exempt from the untrusted-peer ``reject`` policy when the raw peer is loopback (AR-5.3 point 3).
_HEALTH_VERSION_PATHS = frozenset({"/api/v1/health", "/api/v1/version"})
_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1"})


class UntrustedPeerRejected(Exception):
    """AR-5.3 point 3's ``reject`` policy applies to this request.

    ``resolve_client_chain`` itself never raises; this is raised by the caller-side policy
    check in :func:`resolve_client_and_zone`, as the pure function's own docstring leaves it to
    the caller. The middleware catches this and returns ``403 UNTRUSTED_PEER``.
    """

    def __init__(self, remote_addr: str) -> None:
        self.remote_addr = remote_addr
        super().__init__(f"untrusted peer rejected: {remote_addr!r}")


@dataclass(frozen=True)
class RequestContext:
    """Resolved identity, View As state, and client IP/zone for exactly one HTTP request.

    ``real_user`` is who actually signed in (``None`` when the request is anonymous, or when
    the session referenced a user that no longer exists or is disabled -- disabled users'
    sessions are rejected, AR-2.11). ``effective_user`` is the identity used for visibility and
    permission checks: equal to ``real_user`` unless an admin has an active View As target in
    their session, in which case it is the View As target and ``view_as_active`` is True. An admin
    may also View As a *zone* (AR-2.9, owner 2026-11-15): ``zone`` is then that zone instead of the
    one resolved from the client IP, ``view_as_zone`` is True, and View As is active even with no
    user target (the admin sees their own perspective from that zone).
    """

    real_user: UserAccount | None
    effective_user: UserAccount | None
    view_as_active: bool
    client_ip: str
    chain: ChainResolution
    zone: SecurityZone | None
    view_as_zone: bool = False


def proxy_chain_config_from_settings() -> ProxyChainConfig:
    """Build a :class:`ProxyChainConfig` from the current Django settings.

    Cheap and pure; built fresh on every request rather than cached, since settings rarely
    change and the construction cost is negligible (AR-5.3).
    """
    return ProxyChainConfig(
        trust_proxy_headers=bool(settings.PANIC_TRUST_PROXY_HEADERS),
        trusted_proxy_cidrs=tuple(settings.PANIC_TRUSTED_PROXY_CIDRS),
        proxy_ip_header=settings.PANIC_PROXY_IP_HEADER,
        untrusted_peer_policy=settings.PANIC_UNTRUSTED_PEER_POLICY,
        max_hops=settings.PANIC_XFF_MAX_HOPS,
        max_bytes=settings.PANIC_XFF_MAX_BYTES,
    )


def resolve_client_and_zone(request: HttpRequest) -> tuple[ChainResolution, SecurityZone | None]:
    """Resolve the client-IP hop chain and Security Zone for ``request`` (AR-5.3).

    Raises :class:`UntrustedPeerRejected` when the ``reject`` untrusted-peer policy applies and
    the request is not the loopback ``health``/``version`` carve-out. When the true client
    location is unknown for any reason, the zone is the built-in Default zone.
    """
    config = proxy_chain_config_from_settings()
    peer = request.META.get("REMOTE_ADDR", "")
    chain = resolve_client_chain(peer, request.headers, config)

    if chain.decision == "UNTRUSTED_PEER" and config.untrusted_peer_policy == "reject":
        exempt = request.path_info in _HEALTH_VERSION_PATHS and chain.remote_addr in _LOOPBACK_IPS
        if not exempt:
            raise UntrustedPeerRejected(chain.remote_addr)

    db = get_db()
    zone: SecurityZone | None = None
    if chain.location_known:
        zone = resolve_ip_zone(chain.client_ip, zones_repo.list_zones(db)).winning_zone
    if zone is None:
        try:
            zone = zones_repo.get_zone(db, zones_repo.DEFAULT_ZONE_ID)
        except NotFound:
            zone = None
    return chain, zone


def _lookup_active_user(db: object, user_id: str) -> UserAccount | None:
    """``users_repo.get_user``, treating "not found" or "disabled" alike as "no such identity"."""
    try:
        user = users_repo.get_user(db, user_id)  # type: ignore[arg-type]
    except NotFound:
        return None
    return None if user.disabled else user


def build_request_context(request: HttpRequest) -> RequestContext:
    """Resolve everything for ``request``, using only its own session and headers.

    Called exactly once per request (by ``RequestContextMiddleware``); the result is stashed on
    ``request.context``. No part of this function reads or writes any process-level state.
    """
    chain, zone = resolve_client_and_zone(request)

    real_user: UserAccount | None = None
    session = getattr(request, "session", None)
    uid = session.get(SESSION_USER_KEY) if session is not None else None
    if uid:
        real_user = _lookup_active_user(get_db(), str(uid))

    effective_user = real_user
    view_as_active = False
    view_as_zone = False
    if real_user is not None and session is not None and can_use_view_as(real_user):
        view_as_uid = session.get(SESSION_VIEW_AS_KEY)
        if view_as_uid:
            target = _lookup_active_user(get_db(), str(view_as_uid))
            if target is not None:
                effective_user = target
                view_as_active = True
        view_as_zid = session.get(SESSION_VIEW_AS_ZONE_KEY)
        if view_as_zid:
            try:
                zone = zones_repo.get_zone(get_db(), str(view_as_zid))
                view_as_active = view_as_zone = True
            except NotFound:
                pass  # zone deleted meanwhile: fall back to the real one

    return RequestContext(
        real_user=real_user,
        effective_user=effective_user,
        view_as_active=view_as_active,
        client_ip=chain.client_ip,
        chain=chain,
        zone=zone,
        view_as_zone=view_as_zone,
    )


__all__ = [
    "SESSION_USER_KEY",
    "SESSION_VIEW_AS_KEY",
    "SESSION_VIEW_AS_ZONE_KEY",
    "RequestContext",
    "UntrustedPeerRejected",
    "build_request_context",
    "proxy_chain_config_from_settings",
    "resolve_client_and_zone",
]

"""``GET /api/v1/admin/client-ip`` -- trust-chain + zone diagnostics (API.md §6).

``request.context.chain`` already carries everything except the config actually in
effect (``policy``) and every zone CIDR candidate, not just the winner (``candidates``) --
``RequestContext`` deliberately only keeps the *winning* zone. Both are cheap to re-derive here
(admin diagnostics, not a budgeted UI read): ``policy`` straight from settings, ``candidates`` by
calling ``panic_common.zones.resolve_ip_zone`` again with the already-known ``chain.client_ip``.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from panic_common.zones import resolve_ip_zone
from panic_server.api.permissions import IsGlobalAdmin
from panic_server.context import proxy_chain_config_from_settings
from panic_server.store.client import get_db
from panic_server.store.repos import zones as zones_repo


@extend_schema(tags=["admin"], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([IsGlobalAdmin])
def client_ip_view(request: Request) -> Response:
    django_request = request._request
    context = django_request.context
    chain = context.chain
    config = proxy_chain_config_from_settings()

    db = get_db()
    result = resolve_ip_zone(chain.client_ip, zones_repo.list_zones(db)) if chain.location_known else None
    winning = result.winning_zone if result is not None else None
    zone = winning if winning is not None else context.zone
    zone_source = "CIDR" if winning is not None else "DEFAULT"
    matched_cidr = result.matched_cidr if result is not None else None
    candidates = [c.model_dump(mode="json") for c in result.candidates] if result is not None else []

    body: dict[str, Any] = {
        "remote_addr": chain.remote_addr,
        "peer_trusted": chain.peer_trusted,
        "policy": {
            "trust_proxy_headers": config.trust_proxy_headers,
            "header": config.proxy_ip_header,
            "untrusted_peer_policy": config.untrusted_peer_policy,
            "trusted_proxy_cidrs": list(config.trusted_proxy_cidrs),
            "max_hops": config.max_hops,
            "max_bytes": config.max_bytes,
        },
        "raw": {
            "x_forwarded_for": django_request.headers.get("X-Forwarded-For"),
            "forwarded": django_request.headers.get("Forwarded"),
            "x_real_ip": django_request.headers.get("X-Real-IP"),
        },
        "hops": [h.model_dump(mode="json") for h in chain.hops],
        "ignored_left_hops": chain.ignored_left_hops,
        "truncated": chain.truncated,
        "decision": chain.decision,
        "client_ip": chain.client_ip,
        "zone": {"id": zone.id, "name": zone.name, "matched_cidr": matched_cidr} if zone is not None else None,
        "zone_source": zone_source,
        "candidates": candidates,
    }
    return Response(body)


__all__ = ["client_ip_view"]

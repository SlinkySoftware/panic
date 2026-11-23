"""``RequestContextMiddleware``: trusted-proxy IP resolution, Security Zone binding, anti-spoofing,
and the AR-5.3 ``reject`` untrusted-peer policy.

Zones come from ``panic_server.store.repos.zones`` (Mongo); the logic under test is the
``resolve_client_chain`` + ``resolve_ip_zone`` wiring in ``panic_server.context``/``middleware``.
"""

from __future__ import annotations

import json

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory, override_settings
from pymongo.database import Database

from panic_server.context import UntrustedPeerRejected, build_request_context
from panic_server.middleware import RequestContextMiddleware
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)


def test_middleware_resolves_trusted_proxy_client_ip_and_security_zone(mongo_db: Database) -> None:
    zones_repo.create_zone(mongo_db, name="PM-Test-DMZ", priority=150, cidrs=["10.20.0.0/16"])
    factory = RequestFactory()
    request = factory.get(
        "/api/v1/bootstrap",
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_FORWARDED_FOR="10.20.100.25",
    )

    captured: dict[str, object] = {}

    def get_response(req: HttpRequest) -> HttpResponse:
        captured["client_ip"] = getattr(req, "client_ip", None)
        captured["resolved_zone"] = getattr(req, "resolved_zone", None)
        return HttpResponse("ok")

    mw = RequestContextMiddleware(get_response)
    response = mw(request)

    assert captured["client_ip"] == "10.20.100.25"
    zone = captured["resolved_zone"]
    assert zone is not None
    assert zone.name == "PM-Test-DMZ"
    assert response["X-Client-IP"] == "10.20.100.25"
    assert response["X-Security-Zone"] == zone.id


def test_middleware_blocks_header_spoofing_from_untrusted_peer(mongo_db: Database) -> None:
    # A zone CIDR that would match the untrusted peer's own address -- it must NOT win: per
    # AR-5.3 point 3, an untrusted peer's location is always unknown, so it always gets the
    # Default zone, even though its raw IP happens to fall inside a configured zone CIDR.
    zones_repo.create_zone(mongo_db, name="PM-Test-Corp", priority=200, cidrs=["198.51.100.0/24"])
    factory = RequestFactory()
    # 198.51.100.44 is NOT a trusted proxy; its attempt to forge a different client IP via
    # X-Forwarded-For must be ignored.
    request = factory.get(
        "/api/v1/bootstrap",
        REMOTE_ADDR="198.51.100.44",
        HTTP_X_FORWARDED_FOR="10.10.50.14",
    )

    mw = RequestContextMiddleware(lambda _req: HttpResponse("ok"))
    response = mw(request)

    assert getattr(request, "client_ip", None) == "198.51.100.44"
    assert request.context.chain.peer_trusted is False
    assert request.context.chain.decision == "UNTRUSTED_PEER"
    resolved_zone = getattr(request, "resolved_zone", None)
    assert resolved_zone is not None
    assert resolved_zone.id == zones_repo.DEFAULT_ZONE_ID
    assert response["X-Client-IP"] == "198.51.100.44"
    assert response["X-Security-Zone"] == zones_repo.DEFAULT_ZONE_ID


def test_middleware_unknown_location_falls_back_to_default_zone(mongo_db: Database) -> None:
    zones_repo.create_zone(mongo_db, name="PM-Test-Lab", priority=100, cidrs=["172.16.0.0/16"])
    factory = RequestFactory()
    # A trusted peer with no X-Forwarded-For header at all: location unknown (NO_HEADER).
    request = factory.get("/api/v1/health", REMOTE_ADDR="172.16.0.10")

    with override_settings(PANIC_TRUSTED_PROXY_CIDRS=["172.16.0.0/16"]):
        mw = RequestContextMiddleware(lambda _req: HttpResponse("ok"))
        response = mw(request)

    assert getattr(request, "client_ip", None) == "172.16.0.10"
    zone = getattr(request, "resolved_zone", None)
    assert zone is not None and zone.id == zones_repo.DEFAULT_ZONE_ID
    assert response["X-Security-Zone"] == zones_repo.DEFAULT_ZONE_ID


def test_untrusted_peer_reject_policy_returns_403(mongo_db: Database) -> None:
    factory = RequestFactory()
    request = factory.get("/api/v1/bootstrap", REMOTE_ADDR="203.0.113.9")

    with override_settings(PANIC_UNTRUSTED_PEER_POLICY="reject"):
        with pytest.raises(UntrustedPeerRejected):
            build_request_context(request)

        mw = RequestContextMiddleware(lambda _req: HttpResponse("ok"))
        response = mw(request)
    assert response.status_code == 403
    assert json.loads(response.content)["error_code"] == "UNTRUSTED_PEER"


def test_untrusted_peer_reject_policy_exempts_loopback_health_and_version(mongo_db: Database) -> None:
    factory = RequestFactory()
    for path in ("/api/v1/health", "/api/v1/version"):
        request = factory.get(path, REMOTE_ADDR="127.0.0.1")
        with override_settings(PANIC_TRUSTED_PROXY_CIDRS=[], PANIC_UNTRUSTED_PEER_POLICY="reject"):
            context = build_request_context(request)
        assert context.client_ip == "127.0.0.1"


def test_middleware_end_to_end_via_django_client(mongo_db: Database) -> None:
    zones_repo.create_zone(mongo_db, name="PM-Test-Core", priority=100, cidrs=["10.10.50.0/24"])
    with override_settings(
        MIDDLEWARE=[
            "django.middleware.security.SecurityMiddleware",
            "django.middleware.common.CommonMiddleware",
            "panic_server.middleware.RequestIdMiddleware",
            "panic_server.middleware.RequestContextMiddleware",
        ]
    ):
        client = Client()
        resp = client.get(
            "/api/v1/health",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="10.10.50.14",
        )
    assert resp.status_code == 200
    assert resp["X-Client-IP"] == "10.10.50.14"
    assert "X-Request-ID" in resp

"""Tests for ClientIpZoneMiddleware: trusted-proxy IP resolution, Zone binding, and anti-spoofing."""

from __future__ import annotations

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory, override_settings

from panic_server.middleware import ClientIpZoneMiddleware
from panic_server.state import STORE


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    STORE.reset()


def test_middleware_resolves_trusted_proxy_client_ip_and_security_zone() -> None:
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

    mw = ClientIpZoneMiddleware(get_response)
    response = mw(request)

    assert captured["client_ip"] == "10.20.100.25"
    zone = captured["resolved_zone"]
    assert zone is not None
    assert getattr(zone, "id", None) == "zone-dmz"
    assert response["X-Client-IP"] == "10.20.100.25"
    assert response["X-Security-Zone"] == "zone-dmz"


def test_middleware_blocks_header_spoofing_from_untrusted_peer() -> None:
    factory = RequestFactory()
    # 198.51.100.44 is in zone-corp, NOT in trusted_proxy_cidrs; attempts to spoof zone-core IP
    request = factory.get(
        "/api/v1/bootstrap",
        REMOTE_ADDR="198.51.100.44",
        HTTP_X_FORWARDED_FOR="10.10.50.14",
    )

    mw = ClientIpZoneMiddleware(lambda _req: HttpResponse("ok"))
    response = mw(request)

    assert getattr(request, "client_ip", None) == "198.51.100.44"
    assert getattr(request, "client_ip_resolution", None).trusted_proxy is False
    resolved_zone = getattr(request, "resolved_zone", None)
    assert resolved_zone is not None
    assert resolved_zone.id == "zone-corp"
    assert response["X-Client-IP"] == "198.51.100.44"
    assert response["X-Security-Zone"] == "zone-corp"


def test_middleware_unzoned_ip_sets_unzoned_header_and_custom_settings() -> None:
    factory = RequestFactory()
    request = factory.get(
        "/api/v1/health",
        REMOTE_ADDR="172.16.0.10",
        HTTP_X_REAL_IP="2001:db8:99::1",
    )

    with override_settings(
        PANIC_TRUST_PROXY_HEADERS=True,
        PANIC_TRUSTED_PROXY_CIDRS=["172.16.0.0/16"],
        PANIC_PROXY_IP_HEADER="X-Real-IP",
    ):
        mw = ClientIpZoneMiddleware(lambda _req: HttpResponse("ok"))
        response = mw(request)

    assert getattr(request, "client_ip", None) == "2001:db8:99::1"
    assert getattr(request, "resolved_zone", None) is None
    assert response["X-Client-IP"] == "2001:db8:99::1"
    assert response["X-Security-Zone"] == "UNZONED"


@override_settings(
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.middleware.common.CommonMiddleware",
        "panic_server.middleware.RequestIdMiddleware",
        "panic_server.middleware.ClientIpZoneMiddleware",
    ]
)
def test_middleware_end_to_end_via_django_client() -> None:
    client = Client()
    resp = client.get(
        "/api/v1/health",
        REMOTE_ADDR="127.0.0.1",
        HTTP_X_FORWARDED_FOR="10.10.50.14",
    )
    assert resp.status_code == 200
    assert resp["X-Client-IP"] == "10.10.50.14"
    assert resp["X-Security-Zone"] == "zone-core"
    assert "X-Request-ID" in resp

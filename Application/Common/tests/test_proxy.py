"""Unit tests for panic_common.proxy: CIDR membership, trusted-proxy verification, and anti-spoofing XFF parsing."""

from __future__ import annotations

from panic_common.proxy import is_ip_in_cidrs, resolve_client_ip


def test_is_ip_in_cidrs_ipv4_ipv6_and_invalid_inputs() -> None:
    cidrs = ["10.10.0.0/16", "192.0.2.0/24", "2001:db8:10::/48"]
    assert is_ip_in_cidrs("10.10.50.14", cidrs) is True
    assert is_ip_in_cidrs("192.0.2.99", cidrs) is True
    assert is_ip_in_cidrs("2001:db8:10::abcd", cidrs) is True
    assert is_ip_in_cidrs("198.51.100.10", cidrs) is False
    assert is_ip_in_cidrs("2001:db8:99::1", cidrs) is False
    assert is_ip_in_cidrs("not-an-ip", cidrs) is False
    assert is_ip_in_cidrs("10.10.1.1", ["invalid-cidr", "", "10.10.0.0/16"]) is True


def test_untrusted_remote_addr_ignores_spoofed_forwarded_headers() -> None:
    res = resolve_client_ip(
        remote_addr="203.0.113.45",
        headers={"X-Forwarded-For": "10.10.50.14, 192.0.2.10"},
        trust_proxy_headers=True,
        trusted_proxy_cidrs=["127.0.0.1/32", "10.0.0.0/8"],
    )
    assert res.client_ip == "203.0.113.45"
    assert res.remote_addr == "203.0.113.45"
    assert res.trusted_proxy is False
    assert res.header_used is None
    assert res.proxy_chain == []


def test_trusted_proxy_single_and_multi_hop_rightmost_untrusted_ip() -> None:
    # Single hop from loopback reverse proxy
    single = resolve_client_ip(
        remote_addr="127.0.0.1",
        headers={"x-forwarded-for": "198.51.100.25"},
    )
    assert single.client_ip == "198.51.100.25"
    assert single.remote_addr == "127.0.0.1"
    assert single.trusted_proxy is True
    assert single.header_used == "X-Forwarded-For"
    assert single.proxy_chain == ["198.51.100.25"]

    # Multi-hop with attacker spoofing left-most XFF entry behind two trusted proxies
    # Chain: [spoofed 10.10.50.99, real client 198.51.100.77, trusted edge proxy 172.16.1.10]
    multi = resolve_client_ip(
        remote_addr="127.0.0.1",
        headers={"X-Forwarded-For": "10.10.50.99, 198.51.100.77, 172.16.1.10"},
        trusted_proxy_cidrs=["127.0.0.1/32", "172.16.0.0/16"],
    )
    assert multi.client_ip == "198.51.100.77"
    assert multi.trusted_proxy is True
    assert multi.proxy_chain == ["10.10.50.99", "198.51.100.77", "172.16.1.10"]


def test_trusted_proxy_all_trusted_hops_selects_leftmost() -> None:
    res = resolve_client_ip(
        remote_addr="127.0.0.1",
        headers={"X-Forwarded-For": "172.16.1.5, 172.16.1.10"},
        trusted_proxy_cidrs=["127.0.0.1/32", "172.16.0.0/16"],
    )
    assert res.client_ip == "172.16.1.5"
    assert res.trusted_proxy is True


def test_ipv6_proxy_and_client_resolution() -> None:
    res = resolve_client_ip(
        remote_addr="::1",
        headers={"X-Forwarded-For": "2001:db8:20::42, 2001:db8:fe::1"},
        trusted_proxy_cidrs=["::1/128", "2001:db8:fe::/48"],
    )
    assert res.client_ip == "2001:db8:20::42"
    assert res.remote_addr == "::1"
    assert res.trusted_proxy is True
    assert res.proxy_chain == ["2001:db8:20::42", "2001:db8:fe::1"]


def test_custom_header_x_real_ip_and_disabled_proxy_trust() -> None:
    custom = resolve_client_ip(
        remote_addr="10.0.0.5",
        headers={"HTTP_X_REAL_IP": "192.0.2.88"},
        trust_proxy_headers=True,
        trusted_proxy_cidrs=["10.0.0.0/8"],
        proxy_ip_header="X-Real-IP",
    )
    assert custom.client_ip == "192.0.2.88"
    assert custom.header_used == "X-Real-IP"
    assert custom.trusted_proxy is True

    disabled = resolve_client_ip(
        remote_addr="127.0.0.1",
        headers={"X-Forwarded-For": "192.0.2.88"},
        trust_proxy_headers=False,
    )
    assert disabled.client_ip == "127.0.0.1"
    assert disabled.trusted_proxy is False
    assert disabled.header_used is None


def test_malformed_or_missing_headers_fallback_to_clean_remote() -> None:
    missing = resolve_client_ip(remote_addr="", headers={})
    assert missing.client_ip == "127.0.0.1"
    assert missing.trusted_proxy is True
    assert missing.header_used is None

    malformed = resolve_client_ip(
        remote_addr="127.0.0.1",
        headers={"X-Forwarded-For": "garbage, unknown"},
    )
    assert malformed.client_ip == "127.0.0.1"
    assert malformed.trusted_proxy is True
    assert malformed.header_used is None
    assert malformed.proxy_chain == []

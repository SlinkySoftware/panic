"""Unit tests for panic_common.proxy: CIDR membership, trusted-proxy verification, and anti-spoofing XFF parsing."""

from __future__ import annotations

import pytest

from panic_common.proxy import (
    ProxyChainConfig,
    is_ip_in_cidrs,
    resolve_client_chain,
    resolve_client_ip,
)


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


# ---------------------------------------------------------------------------
# resolve_client_chain (ARCHITECTURE §5, AR-5.3 / AR-5.5) — table-driven, 40+ cases.
# ---------------------------------------------------------------------------

TRUSTED = ("127.0.0.1/32", "::1/128", "172.16.0.0/16", "10.0.0.0/8")


def _cfg(**overrides: object) -> ProxyChainConfig:
    kwargs: dict[str, object] = {"trusted_proxy_cidrs": TRUSTED}
    kwargs.update(overrides)
    return ProxyChainConfig(**kwargs)  # type: ignore[arg-type]


# Each case: (id, peer, headers, config, expected_decision, expected_client_ip, expected_location_known)
CASES: list[tuple[str, str, dict[str, str], ProxyChainConfig, str, str, bool]] = [
    # --- HEADERS_DISABLED --------------------------------------------------
    (
        "headers_disabled_trusted_peer",
        "10.0.0.5",
        {"X-Forwarded-For": "198.51.100.9"},
        _cfg(trust_proxy_headers=False),
        "HEADERS_DISABLED",
        "10.0.0.5",
        True,
    ),
    (
        "headers_disabled_untrusted_peer_still_resolved_normally",
        "198.51.100.9",
        {"X-Forwarded-For": "10.0.0.5"},
        _cfg(trust_proxy_headers=False),
        "HEADERS_DISABLED",
        "198.51.100.9",
        True,
    ),
    (
        "headers_disabled_ignores_malformed_header_too",
        "10.0.0.5",
        {"X-Forwarded-For": "unknown, garbage"},
        _cfg(trust_proxy_headers=False),
        "HEADERS_DISABLED",
        "10.0.0.5",
        True,
    ),
    # --- UNTRUSTED_PEER -----------------------------------------------------
    (
        "untrusted_peer_spoofed_xff_ignored",
        "203.0.113.45",
        {"X-Forwarded-For": "10.0.0.5, 198.51.100.9"},
        _cfg(),
        "UNTRUSTED_PEER",
        "203.0.113.45",
        False,
    ),
    (
        "untrusted_peer_no_headers_at_all",
        "203.0.113.45",
        {},
        _cfg(),
        "UNTRUSTED_PEER",
        "203.0.113.45",
        False,
    ),
    (
        "untrusted_peer_ipv6",
        "2001:db8:bad::1",
        {"X-Forwarded-For": "10.0.0.5"},
        _cfg(),
        "UNTRUSTED_PEER",
        "2001:db8:bad::1",
        False,
    ),
    (
        "untrusted_peer_policy_reject_does_not_change_pure_decision",
        "203.0.113.45",
        {},
        _cfg(untrusted_peer_policy="reject"),
        "UNTRUSTED_PEER",
        "203.0.113.45",
        False,
    ),
    # --- NO_HEADER -----------------------------------------------------------
    (
        "no_header_key_missing",
        "10.0.0.5",
        {},
        _cfg(),
        "NO_HEADER",
        "10.0.0.5",
        False,
    ),
    (
        "no_header_empty_string",
        "10.0.0.5",
        {"X-Forwarded-For": ""},
        _cfg(),
        "NO_HEADER",
        "10.0.0.5",
        False,
    ),
    (
        "no_header_whitespace_only",
        "10.0.0.5",
        {"X-Forwarded-For": "   "},
        _cfg(),
        "NO_HEADER",
        "10.0.0.5",
        False,
    ),
    # --- FIRST_UNTRUSTED_HOP --------------------------------------------------
    (
        "single_hop_simple",
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.25"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.25",
        True,
    ),
    (
        "four_tier_chain_corp_proxy_and_web_trusted",
        "172.16.1.10",
        {"X-Forwarded-For": "198.51.100.77, 172.16.1.5"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.77",
        True,
    ),
    (
        "client_spoofing_leftmost_entry_is_ignored",
        "127.0.0.1",
        {"X-Forwarded-For": "10.10.50.99, 198.51.100.77, 172.16.1.10"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.77",
        True,
    ),
    (
        "jump_host_inside_overly_broad_trusted_range_pitfall",
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.77, 10.55.4.9"},
        _cfg(),  # 10.0.0.0/8 is trusted, so the 10.55.4.9 "jump host" is skipped like a proxy
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.77",
        True,
    ),
    (
        "ipv6_bracketed_with_port",
        "::1",
        {"X-Forwarded-For": "[2001:db8:20::42]:51234"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "2001:db8:20::42",
        True,
    ),
    (
        "ipv4_mapped_ipv6_normalised",
        "127.0.0.1",
        {"X-Forwarded-For": "::ffff:198.51.100.9"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.9",
        True,
    ),
    (
        "ipv4_with_port",
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.9:443"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.9",
        True,
    ),
    (
        "repeated_header_lines_joined_by_comma",
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.9, 172.16.1.1, 172.16.1.2"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.9",
        True,
    ),
    (
        "forwarded_header_basic",
        "127.0.0.1",
        {"Forwarded": "for=198.51.100.60;proto=https;by=172.16.1.1"},
        _cfg(proxy_ip_header="Forwarded"),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.60",
        True,
    ),
    (
        "forwarded_header_multi_hop",
        "172.16.1.10",
        {"Forwarded": "for=198.51.100.61, for=172.16.1.5"},
        _cfg(proxy_ip_header="Forwarded"),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.61",
        True,
    ),
    (
        "forwarded_header_quoted_ipv6_with_port",
        "127.0.0.1",
        {"Forwarded": 'for="[2001:db8:cafe::17]:4711"'},
        _cfg(proxy_ip_header="Forwarded"),
        "FIRST_UNTRUSTED_HOP",
        "2001:db8:cafe::17",
        True,
    ),
    (
        "forwarded_header_case_insensitive_param",
        "127.0.0.1",
        {"Forwarded": "For=192.0.2.9;Proto=https"},
        _cfg(proxy_ip_header="Forwarded"),
        "FIRST_UNTRUSTED_HOP",
        "192.0.2.9",
        True,
    ),
    # --- ALL_HOPS_TRUSTED ------------------------------------------------------
    (
        "all_hops_trusted_xff",
        "172.16.1.10",
        {"X-Forwarded-For": "172.16.1.5, 172.16.1.6"},
        _cfg(),
        "ALL_HOPS_TRUSTED",
        "172.16.1.5",
        False,
    ),
    (
        "all_hops_trusted_single_hop",
        "127.0.0.1",
        {"X-Forwarded-For": "10.0.0.9"},
        _cfg(),
        "ALL_HOPS_TRUSTED",
        "10.0.0.9",
        False,
    ),
    (
        "all_hops_trusted_forwarded",
        "127.0.0.1",
        {"Forwarded": "for=10.0.0.1, for=10.0.0.2"},
        _cfg(proxy_ip_header="Forwarded"),
        "ALL_HOPS_TRUSTED",
        "10.0.0.1",
        False,
    ),
    # --- MALFORMED_HOP: junk and `unknown` tokens -------------------------------
    (
        "malformed_unknown_token",
        "127.0.0.1",
        {"X-Forwarded-For": "unknown"},
        _cfg(),
        "MALFORMED_HOP",
        "127.0.0.1",
        False,
    ),
    (
        "malformed_garbage_token",
        "127.0.0.1",
        {"X-Forwarded-For": "not-an-ip-at-all"},
        _cfg(),
        "MALFORMED_HOP",
        "127.0.0.1",
        False,
    ),
    (
        "malformed_obfuscated_forwarded_identifier",
        "127.0.0.1",
        {"Forwarded": "for=_hiddenproxy"},
        _cfg(proxy_ip_header="Forwarded"),
        "MALFORMED_HOP",
        "127.0.0.1",
        False,
    ),
    (
        "malformed_empty_token_in_chain",
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.1, , 172.16.1.1"},
        _cfg(),
        "MALFORMED_HOP",
        "172.16.1.1",
        False,
    ),
    (
        "malformed_after_trusted_hops_consumed",
        "127.0.0.1",
        {"X-Forwarded-For": "junk, 172.16.1.1, 172.16.1.2"},
        _cfg(),
        "MALFORMED_HOP",
        "172.16.1.1",
        False,
    ),
    (
        "forwarded_element_missing_for_param",
        "127.0.0.1",
        {"Forwarded": "proto=https;by=172.16.1.1"},
        _cfg(proxy_ip_header="Forwarded"),
        "MALFORMED_HOP",
        "127.0.0.1",
        False,
    ),
    # --- truncation / limits -----------------------------------------------------
    (
        "max_hops_exceeded_only_rightmost_considered",
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.1, 198.51.100.2, 198.51.100.3, 172.16.1.1"},
        _cfg(max_hops=2),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.3",
        True,
    ),
    (
        "max_bytes_exceeded_truncated_from_left_cuts_leftover_token_to_garbage",
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.200, " + ", ".join(["172.16.1.1"] * 20)},
        _cfg(max_bytes=24),
        "MALFORMED_HOP",
        "172.16.1.1",
        False,
    ),
    (
        "invalid_peer_falls_back_to_loopback",
        "not-an-ip",
        {"X-Forwarded-For": "198.51.100.5"},
        _cfg(),
        "FIRST_UNTRUSTED_HOP",
        "198.51.100.5",
        True,
    ),
    (
        "untrusted_peer_malformed_header_still_ignored",
        "203.0.113.1",
        {"X-Forwarded-For": "garbage, unknown"},
        _cfg(),
        "UNTRUSTED_PEER",
        "203.0.113.1",
        False,
    ),
]


@pytest.mark.parametrize(
    ("peer", "headers", "config", "expected_decision", "expected_client_ip", "expected_location_known"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_resolve_client_chain_cases(
    peer: str,
    headers: dict[str, str],
    config: ProxyChainConfig,
    expected_decision: str,
    expected_client_ip: str,
    expected_location_known: bool,
) -> None:
    res = resolve_client_chain(peer, headers, config)
    assert res.decision == expected_decision
    assert res.client_ip == expected_client_ip
    assert res.location_known is expected_location_known


def test_api_admin_client_ip_shape_matches_documented_example() -> None:
    res = resolve_client_chain(
        "192.0.2.30",
        {"X-Forwarded-For": "203.0.113.9, 198.51.100.23, 192.0.2.10, 192.0.2.20"},
        _cfg(trusted_proxy_cidrs=("192.0.2.10/32", "192.0.2.20/32", "192.0.2.30/32")),
    )
    assert [h.position for h in res.hops] == [4, 3, 2, 1]
    assert [h.ip for h in res.hops] == ["192.0.2.30", "192.0.2.20", "192.0.2.10", "198.51.100.23"]
    assert [h.trusted for h in res.hops] == [True, True, True, False]
    assert res.hops[-1].selected is True
    assert all(not h.selected for h in res.hops[:-1])
    assert res.ignored_left_hops == 1
    assert res.decision == "FIRST_UNTRUSTED_HOP"
    assert res.client_ip == "198.51.100.23"
    assert res.header_used == "X-Forwarded-For"


def test_untrusted_peer_header_and_hops_are_empty() -> None:
    res = resolve_client_chain("203.0.113.1", {"X-Forwarded-For": "10.0.0.1"}, _cfg())
    assert res.header_used is None
    assert res.hops == []


def test_max_bytes_truncation_sets_truncated_flag() -> None:
    header = "198.51.100.200, " + ", ".join(["172.16.1.1"] * 20)
    res = resolve_client_chain("127.0.0.1", {"X-Forwarded-For": header}, _cfg(max_bytes=24))
    assert res.truncated is True


def test_max_hops_truncation_sets_truncated_flag() -> None:
    res = resolve_client_chain(
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.1, 198.51.100.2, 198.51.100.3, 172.16.1.1"},
        _cfg(max_hops=2),
    )
    assert res.truncated is True


def test_no_truncation_when_within_limits() -> None:
    res = resolve_client_chain(
        "127.0.0.1",
        {"X-Forwarded-For": "198.51.100.1, 172.16.1.1"},
        _cfg(max_hops=16, max_bytes=4096),
    )
    assert res.truncated is False


def test_header_used_reflects_configured_header_name() -> None:
    xff = resolve_client_chain("127.0.0.1", {"X-Forwarded-For": "198.51.100.1"}, _cfg())
    assert xff.header_used == "X-Forwarded-For"
    forwarded = resolve_client_chain(
        "127.0.0.1", {"Forwarded": "for=198.51.100.1"}, _cfg(proxy_ip_header="Forwarded")
    )
    assert forwarded.header_used == "Forwarded"


def test_header_lookup_is_case_insensitive_and_supports_django_meta_style() -> None:
    lower = resolve_client_chain("127.0.0.1", {"x-forwarded-for": "198.51.100.1"}, _cfg())
    assert lower.decision == "FIRST_UNTRUSTED_HOP"
    assert lower.client_ip == "198.51.100.1"

    meta_style = resolve_client_chain("127.0.0.1", {"HTTP_X_FORWARDED_FOR": "198.51.100.1"}, _cfg())
    assert meta_style.decision == "FIRST_UNTRUSTED_HOP"
    assert meta_style.client_ip == "198.51.100.1"


def test_unknown_location_decisions_constant_matches_all_non_resolved_outcomes() -> None:
    from panic_common.proxy import UNKNOWN_LOCATION_DECISIONS

    assert {
        "UNTRUSTED_PEER",
        "NO_HEADER",
        "ALL_HOPS_TRUSTED",
        "MALFORMED_HOP",
    } == UNKNOWN_LOCATION_DECISIONS
    for case in CASES:
        decision = case[4]
        location_known = case[6]
        assert location_known is (decision not in UNKNOWN_LOCATION_DECISIONS)

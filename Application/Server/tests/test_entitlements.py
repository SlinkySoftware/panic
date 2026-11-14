"""Live JIT entitlement checks: TTL cache, timeout fallback, gates, API and launch enforcement (T-S5-01)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client, override_settings

from panic_common.entitlements import (
    UNAVAILABLE_MESSAGE,
    EntitlementChecker,
    EntitlementDecision,
    EntitlementGate,
    EntitlementRule,
    EntitlementStatus,
    evaluate_gate,
    parse_rules,
)
from panic_common.models import Protocol
from panic_server import entitlements_service
from panic_server.state import STORE


class _Counting:
    name = "counting"

    def __init__(self, result: bool = True, delay: float = 0.0, error: bool = False) -> None:
        self.calls = 0
        self.result, self.delay, self.error = result, delay, error

    def check(self, username: str, entitlement: str) -> bool:
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise ConnectionError("down")
        return self.result


def test_ttl_cache_expires_and_refresh_bypasses() -> None:
    now = [1000.0]
    provider = _Counting()
    checker = EntitlementChecker(provider, ttl_s=30, timeout_s=1, clock=lambda: now[0])
    first = checker.check("alex", "prod-rdp")
    assert first.status == EntitlementStatus.GRANTED and not first.cached
    assert checker.check("alex", "prod-rdp").cached
    assert provider.calls == 1
    now[0] += 29
    assert checker.check("alex", "prod-rdp").cached
    now[0] += 2
    assert not checker.check("alex", "prod-rdp").cached
    assert provider.calls == 2
    checker.check("alex", "prod-rdp", refresh=True)
    assert provider.calls == 3
    assert checker.cache.invalidate("alex") == 1


def test_timeout_and_errors_fail_safe_within_deadline() -> None:
    slow = EntitlementChecker(_Counting(delay=1.0), ttl_s=30, timeout_s=0.1)
    started = time.monotonic()
    decisions = slow.check_many("alex", ["a", "b", "c"])
    assert time.monotonic() - started < 0.6
    assert {d.status for d in decisions.values()} == {EntitlementStatus.UNAVAILABLE}
    assert slow.cache.get(("alex", "a")) is None  # unavailable answers are never cached

    broken = EntitlementChecker(_Counting(error=True), ttl_s=30, timeout_s=1)
    d = broken.check("alex", "a")
    assert d.status == EntitlementStatus.UNAVAILABLE and "ConnectionError" in d.detail


def _decision(status: EntitlementStatus) -> EntitlementDecision:
    return EntitlementDecision("alex", "e", status, "p", 0.0)


def test_gate_evaluation_matrix() -> None:
    warn = EntitlementRule("e", EntitlementGate.WARN)
    block = EntitlementRule("e", EntitlementGate.BLOCK)
    assert evaluate_gate(block, _decision(EntitlementStatus.GRANTED)).allowed
    assert not evaluate_gate(block, _decision(EntitlementStatus.DENIED)).allowed
    soft = evaluate_gate(warn, _decision(EntitlementStatus.DENIED))
    assert soft.allowed and "e" in soft.message
    unavailable = evaluate_gate(block, _decision(EntitlementStatus.UNAVAILABLE))
    assert unavailable.allowed and unavailable.message == UNAVAILABLE_MESSAGE
    assert not evaluate_gate(block, _decision(EntitlementStatus.UNAVAILABLE), fail_closed=True).allowed


def test_parse_rules_validation() -> None:
    rules = parse_rules({"cat-1": {"entitlement": "x", "gate": "block"}, "cat-2": {"entitlement": "y"}})
    assert rules["cat-1"].gate == EntitlementGate.BLOCK and rules["cat-2"].gate == EntitlementGate.WARN
    with pytest.raises(ValueError):
        parse_rules({"cat-1": {"gate": "WARN"}})
    with pytest.raises(ValueError):
        parse_rules({"cat-1": {"entitlement": "x", "gate": "MAYBE"}})


@pytest.fixture
def jit() -> Iterator[dict[str, Any]]:
    rdp = next(c for c in STORE.catalog if c.protocol == Protocol.RDP)
    other = next(c for c in STORE.catalog if c.id != rdp.id)
    user = STORE.active_user.username
    cfg = {
        "PANIC_JIT_ENTITLEMENTS_ENABLED": True,
        "PANIC_ENTITLEMENT_PROVIDER": "static",
        "PANIC_ENTITLEMENT_STATIC_GRANTS": json.dumps({user: ["soft-ent"]}),
        "PANIC_ENTITLEMENT_RULES": json.dumps(
            {rdp.id: {"entitlement": "hard-ent", "gate": "BLOCK"}, other.id: {"entitlement": "soft-ent"}}
        ),
    }
    entitlements_service.reset_checker()
    with override_settings(**cfg):
        yield {"rdp": rdp.id, "other": other.id}
    entitlements_service.reset_checker()


def test_entitlements_api_and_rdp_block(jit: dict[str, Any]) -> None:
    client = Client()
    body = client.get("/api/v1/entitlements").json()
    assert body["enabled"] is True
    items = body["items"]
    assert items[jit["rdp"]]["allowed"] is False
    assert items[jit["rdp"]]["decision"]["status"] == "DENIED"
    assert items[jit["other"]]["allowed"] is True
    assert client.get("/api/v1/entitlements").json()["items"][jit["other"]]["decision"]["cached"] is True
    refreshed = client.post("/api/v1/entitlements", json.dumps({"action": "refresh"}), content_type="application/json")
    assert refreshed.json()["items"][jit["other"]]["decision"]["cached"] is False

    blocked = client.get(f"/api/v1/launch/rdp/{jit['rdp']}.rdp")
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "ENTITLEMENT_DENIED"
    assert "launch.entitlement.denied" in [a.action for a in STORE.query_audit(limit=5)]


def test_jit_disabled_is_a_no_op() -> None:
    client = Client()
    assert client.get("/api/v1/entitlements").json() == {"enabled": False, "items": {}}
    rdp = next(c for c in STORE.catalog if c.protocol == Protocol.RDP)
    assert client.get(f"/api/v1/launch/rdp/{rdp.id}.rdp").status_code == 200


def test_provider_outage_does_not_block_launch(jit: dict[str, Any]) -> None:
    entitlements_service.reset_checker()
    with override_settings(
        PANIC_ENTITLEMENT_PROVIDER="rest", PANIC_ENTITLEMENT_REST_URL="https://pdp.example.com/check"
    ):

        def boom(*_: Any, **__: Any) -> Any:
            raise ConnectionError("unreachable")

        from unittest import mock

        with mock.patch.object(entitlements_service.httpx, "get", boom):
            resp = Client().get(f"/api/v1/launch/rdp/{jit['rdp']}.rdp")
    assert resp.status_code == 200
    assert resp["X-PANIC-Entitlement-Warning"] == UNAVAILABLE_MESSAGE

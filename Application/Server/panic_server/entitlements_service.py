"""Live JIT entitlement providers and the process-wide checker (T-S5-01).

Providers (``PANIC_ENTITLEMENT_PROVIDER``):

- ``static``: grants from ``PANIC_ENTITLEMENT_STATIC_GRANTS`` JSON (``{"username": ["entitlement", ...]}``).
- ``ldap``: LDAP/AD group membership; the entitlement is a group name under
  ``PANIC_ENTITLEMENT_LDAP_GROUP_BASE_DN`` (connection settings from ``PANIC_LDAP_*``).
- ``rest``: HTTP policy decision point (AAA / RADIUS gateway, OIDC introspection proxy, ...):
  ``GET <PANIC_ENTITLEMENT_REST_URL>?username=..&entitlement=..`` returning ``{"granted": bool}``.

Per-item rules come from ``PANIC_ENTITLEMENT_RULES`` (JSON, see ``panic_common.entitlements.parse_rules``).
"""

from __future__ import annotations

import json
import threading
from typing import Any

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from panic_common.entitlements import (
    EntitlementChecker,
    EntitlementDecision,
    EntitlementProvider,
    EntitlementRule,
    GateOutcome,
    evaluate_gate,
    parse_rules,
)


class StaticProvider:
    name = "static"

    def __init__(self, grants: dict[str, list[str]]) -> None:
        self._grants = {u: set(ents) for u, ents in grants.items()}

    def check(self, username: str, entitlement: str) -> bool:
        return entitlement in self._grants.get(username, set())


class RestPolicyProvider:
    name = "rest"

    def __init__(self, url: str, token: str, timeout_s: float) -> None:
        if not url:
            raise ImproperlyConfigured("PANIC_ENTITLEMENT_REST_URL is required for the rest provider")
        self.url, self.token, self.timeout_s = url, token, timeout_s

    def check(self, username: str, entitlement: str) -> bool:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = httpx.get(
            self.url,
            params={"username": username, "entitlement": entitlement},
            headers=headers,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        return isinstance(body, dict) and body.get("granted") is True


class LdapGroupProvider:
    name = "ldap"

    def __init__(self, group_base_dn: str) -> None:
        if not group_base_dn:
            raise ImproperlyConfigured("PANIC_ENTITLEMENT_LDAP_GROUP_BASE_DN is required for the ldap provider")
        self.group_base_dn = group_base_dn

    def check(self, username: str, entitlement: str) -> bool:
        from ldap3 import SUBTREE
        from ldap3.utils.conv import escape_filter_chars

        from panic_server.auth.ldap_auth import _connection, _server

        conn = _connection(_server(), settings.PANIC_LDAP_BIND_DN or None, settings.PANIC_LDAP_BIND_PASSWORD or None)
        try:
            if not conn.bind():
                raise ConnectionError("LDAP service bind failed")
            user_filter = settings.PANIC_LDAP_USER_FILTER.format(username=escape_filter_chars(username))
            conn.search(settings.PANIC_LDAP_USER_BASE_DN, user_filter, SUBTREE, attributes=[], size_limit=2)
            entries = [e for e in conn.response or [] if e.get("type") == "searchResEntry"]
            if len(entries) != 1:
                return False
            user_dn = str(entries[0]["dn"])
            group_filter = "(&({attr}={ent})(|(member={dn})(uniqueMember={dn})(memberUid={user})))".format(
                attr=settings.PANIC_LDAP_GROUP_NAME_ATTR,
                ent=escape_filter_chars(entitlement),
                dn=escape_filter_chars(user_dn),
                user=escape_filter_chars(username),
            )
            conn.search(self.group_base_dn, group_filter, SUBTREE, attributes=[], size_limit=1)
            return any(e.get("type") == "searchResEntry" for e in conn.response or [])
        finally:
            conn.unbind()


def build_provider() -> EntitlementProvider:
    kind = settings.PANIC_ENTITLEMENT_PROVIDER
    if kind == "static":
        grants = json.loads(settings.PANIC_ENTITLEMENT_STATIC_GRANTS or "{}")
        return StaticProvider({str(k): [str(e) for e in v] for k, v in grants.items()})
    if kind == "rest":
        return RestPolicyProvider(
            settings.PANIC_ENTITLEMENT_REST_URL,
            settings.PANIC_ENTITLEMENT_REST_TOKEN,
            float(settings.PANIC_ENTITLEMENT_TIMEOUT_S),
        )
    if kind == "ldap":
        return LdapGroupProvider(settings.PANIC_ENTITLEMENT_LDAP_GROUP_BASE_DN)
    raise ImproperlyConfigured(f"PANIC_ENTITLEMENT_PROVIDER must be static|ldap|rest, got {kind!r}")


_checker: EntitlementChecker | None = None
_checker_lock = threading.Lock()


def enabled() -> bool:
    return bool(settings.PANIC_JIT_ENTITLEMENTS_ENABLED)


def get_checker() -> EntitlementChecker:
    global _checker
    with _checker_lock:
        if _checker is None:
            _checker = EntitlementChecker(
                build_provider(),
                ttl_s=float(settings.PANIC_ENTITLEMENT_CACHE_TTL_S),
                timeout_s=float(settings.PANIC_ENTITLEMENT_TIMEOUT_S),
            )
        return _checker


def reset_checker() -> None:
    """Drop the singleton (tests / settings changes)."""
    global _checker
    with _checker_lock:
        _checker = None


def rules() -> dict[str, EntitlementRule]:
    raw = settings.PANIC_ENTITLEMENT_RULES or "{}"
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ImproperlyConfigured(f"PANIC_ENTITLEMENT_RULES is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ImproperlyConfigured("PANIC_ENTITLEMENT_RULES must be a JSON object")
    try:
        return parse_rules(data)
    except ValueError as e:
        raise ImproperlyConfigured(str(e)) from e


def evaluate_items(username: str, item_ids: list[str], refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return ``{item_id: {gate, entitlement, decision, allowed, message}}`` for gated items only."""
    if not enabled():
        return {}
    item_rules = {i: r for i, r in rules().items() if i in set(item_ids)}
    if not item_rules:
        return {}
    decisions = get_checker().check_many(username, [r.entitlement for r in item_rules.values()], refresh)
    out: dict[str, dict[str, Any]] = {}
    for item_id, rule in item_rules.items():
        decision = decisions[rule.entitlement]
        outcome = evaluate_gate(rule, decision, settings.PANIC_ENTITLEMENT_FAIL_CLOSED)
        out[item_id] = _payload(rule, decision, outcome)
    return out


def check_launch(username: str, item_id: str) -> GateOutcome | None:
    """Gate outcome for launching ``item_id`` (``None`` when ungated or JIT is disabled)."""
    if not enabled():
        return None
    rule = rules().get(item_id)
    if rule is None:
        return None
    decision = get_checker().check(username, rule.entitlement)
    return evaluate_gate(rule, decision, settings.PANIC_ENTITLEMENT_FAIL_CLOSED)


def _payload(rule: EntitlementRule, decision: EntitlementDecision, outcome: GateOutcome) -> dict[str, Any]:
    return {
        "gate": str(rule.gate),
        "entitlement": rule.entitlement,
        "allowed": outcome.allowed,
        "message": outcome.message,
        "decision": decision.as_dict(),
    }

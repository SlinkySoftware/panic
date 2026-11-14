"""Live Just-In-Time (JIT) entitlement checks: provider protocol, short-TTL cache, strict timeouts,
and per-item ``WARN`` / ``BLOCK`` gate evaluation (T-S5-01).

Pure library (AR-1.1): concrete network adapters live in ``panic_server.entitlements_service``.
A provider failure or timeout never raises to the caller; it yields ``UNAVAILABLE``
("Entitlement Check Unavailable") so dashboard rendering is never blocked.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Protocol

UNAVAILABLE_MESSAGE = "Entitlement Check Unavailable"


class EntitlementStatus(StrEnum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    UNAVAILABLE = "UNAVAILABLE"


class EntitlementGate(StrEnum):
    WARN = "WARN"  # soft gate: launch allowed with a warning when not granted
    BLOCK = "BLOCK"  # hard gate: launch refused when denied


class EntitlementProvider(Protocol):
    name: str

    def check(self, username: str, entitlement: str) -> bool:
        """Return True when ``username`` currently holds ``entitlement``. May raise on failure."""
        ...


@dataclass(frozen=True)
class EntitlementRule:
    entitlement: str
    gate: EntitlementGate = EntitlementGate.WARN


@dataclass(frozen=True)
class EntitlementDecision:
    username: str
    entitlement: str
    status: EntitlementStatus
    provider: str
    checked_at: float
    cached: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "entitlement": self.entitlement,
            "status": str(self.status),
            "provider": self.provider,
            "checked_at": self.checked_at,
            "cached": self.cached,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GateOutcome:
    allowed: bool
    gate: EntitlementGate
    status: EntitlementStatus
    message: str = ""


def parse_rules(raw: Mapping[str, Any]) -> dict[str, EntitlementRule]:
    """Parse ``{"<catalog item id>": {"entitlement": "...", "gate": "WARN|BLOCK"}}``.

    Raises ``ValueError`` on malformed entries.
    """
    rules: dict[str, EntitlementRule] = {}
    for item_id, spec in raw.items():
        if not isinstance(spec, Mapping) or not str(spec.get("entitlement", "")).strip():
            raise ValueError(f"entitlement rule for {item_id!r} needs a non-empty 'entitlement'")
        gate_raw = str(spec.get("gate", "WARN")).upper()
        if gate_raw not in EntitlementGate.__members__:
            raise ValueError(f"entitlement rule for {item_id!r} has invalid gate {gate_raw!r}")
        rules[str(item_id)] = EntitlementRule(str(spec["entitlement"]).strip(), EntitlementGate(gate_raw))
    return rules


def evaluate_gate(rule: EntitlementRule, decision: EntitlementDecision, fail_closed: bool = False) -> GateOutcome:
    """Combine a rule and a decision into a launch outcome.

    ``UNAVAILABLE`` is allowed with a warning unless ``fail_closed`` is set for ``BLOCK`` gates.
    """
    if decision.status == EntitlementStatus.GRANTED:
        return GateOutcome(True, rule.gate, decision.status)
    if decision.status == EntitlementStatus.UNAVAILABLE:
        blocked = rule.gate == EntitlementGate.BLOCK and fail_closed
        return GateOutcome(not blocked, rule.gate, decision.status, UNAVAILABLE_MESSAGE)
    message = f"Missing just-in-time entitlement '{rule.entitlement}'"
    return GateOutcome(rule.gate == EntitlementGate.WARN, rule.gate, decision.status, message)


class TTLCache:
    """Thread-safe ``(username, entitlement) -> decision`` cache with absolute expiry."""

    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._data: dict[tuple[str, str], tuple[float, EntitlementDecision]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> EntitlementDecision | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            expires, decision = hit
            if self._clock() >= expires:
                del self._data[key]
                return None
            return decision

    def set(self, key: tuple[str, str], decision: EntitlementDecision) -> None:
        if self.ttl_s <= 0:
            return
        with self._lock:
            self._data[key] = (self._clock() + self.ttl_s, decision)

    def invalidate(self, username: str | None = None) -> int:
        """Drop all entries (or only ``username``'s). Returns the number removed."""
        with self._lock:
            keys = [k for k in self._data if username is None or k[0] == username]
            for k in keys:
                del self._data[k]
            return len(keys)


class EntitlementChecker:
    """Runs provider checks with a hard timeout and caches definitive (granted/denied) answers."""

    def __init__(
        self,
        provider: EntitlementProvider,
        ttl_s: float = 30,
        timeout_s: float = 3,
        clock: Callable[[], float] = time.monotonic,
        max_workers: int = 8,
    ) -> None:
        self.provider = provider
        self.timeout_s = timeout_s
        self.cache = TTLCache(ttl_s, clock)
        self._wall = time.time
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="panic-jit")

    def check(self, username: str, entitlement: str, refresh: bool = False) -> EntitlementDecision:
        return self.check_many(username, [entitlement], refresh)[entitlement]

    def check_many(
        self, username: str, entitlements: list[str], refresh: bool = False
    ) -> dict[str, EntitlementDecision]:
        """Check several entitlements concurrently; total wall time is bounded by ``timeout_s``."""
        out: dict[str, EntitlementDecision] = {}
        pending: dict[str, Future[bool]] = {}
        for ent in dict.fromkeys(entitlements):
            cached = None if refresh else self.cache.get((username, ent))
            if cached is not None:
                out[ent] = replace(cached, cached=True)
            else:
                pending[ent] = self._executor.submit(self.provider.check, username, ent)
        deadline = time.monotonic() + self.timeout_s
        for ent, future in pending.items():
            try:
                granted = bool(future.result(timeout=max(0.0, deadline - time.monotonic())))
            except FutureTimeout:
                future.cancel()
                out[ent] = self._unavailable(username, ent, f"provider timed out after {self.timeout_s}s")
                continue
            except Exception as e:  # provider failures must never break rendering
                out[ent] = self._unavailable(username, ent, f"provider error: {type(e).__name__}")
                continue
            decision = EntitlementDecision(
                username=username,
                entitlement=ent,
                status=EntitlementStatus.GRANTED if granted else EntitlementStatus.DENIED,
                provider=self.provider.name,
                checked_at=self._wall(),
            )
            self.cache.set((username, ent), decision)
            out[ent] = decision
        return out

    def _unavailable(self, username: str, entitlement: str, detail: str) -> EntitlementDecision:
        return EntitlementDecision(
            username=username,
            entitlement=entitlement,
            status=EntitlementStatus.UNAVAILABLE,
            provider=self.provider.name,
            checked_at=self._wall(),
            detail=detail,
        )

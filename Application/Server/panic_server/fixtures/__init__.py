"""Deterministic seed fixtures for ``manage.py panic_seed`` (T-S6-03).

Two profiles, each a pure function returning a :class:`Fixture` of
``panic_common.models`` instances -- no I/O, no Mongo, no randomness tied to wall-clock
time, so re-running a profile's builder always produces byte-identical data. Applying a
``Fixture`` to the database is the seed command's job (``panic_server.store`` is the only
thing allowed to touch Mongo, AR-4.1).

Every hostname/IP/CIDR used by either profile is fictional: ``example.com``/``example.net``,
RFC 5737 (``192.0.2.0/24``, ``198.51.100.0/24``, ``203.0.113.0/24``) or RFC 3849
(``2001:db8::/32``). No real company, host or person names.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from panic_common.models import (
    CatalogItem,
    Dashboard,
    EndpointList,
    SecurityZone,
    SiteDefinition,
    SystemSettings,
    TeamDefinition,
    UserAccount,
)


@dataclass(frozen=True)
class Fixture:
    """Everything a seed profile produces, ready to be upserted collection-by-collection."""

    sites: list[SiteDefinition] = field(default_factory=list)
    teams: list[TeamDefinition] = field(default_factory=list)
    zones: list[SecurityZone] = field(default_factory=list)
    users: list[UserAccount] = field(default_factory=list)
    catalog: list[CatalogItem] = field(default_factory=list)
    lists: list[EndpointList] = field(default_factory=list)
    dashboards: list[Dashboard] = field(default_factory=list)
    system_settings: SystemSettings | None = None


def _build_demo() -> Fixture:
    from panic_server.fixtures import demo

    return demo.build()


def _build_loadtest() -> Fixture:
    from panic_server.fixtures import loadtest

    return loadtest.build()


#: ``--profile`` name -> builder. Imported lazily so importing this package never pulls in
#: the (larger) loadtest generator unless it's actually requested.
PROFILES: dict[str, Callable[[], Fixture]] = {
    "demo": _build_demo,
    "loadtest": _build_loadtest,
}


def build_profile(name: str) -> Fixture:
    try:
        builder = PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown seed profile {name!r}; choices are {sorted(PROFILES)}") from None
    return builder()


__all__ = ["PROFILES", "Fixture", "build_profile"]

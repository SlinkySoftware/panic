"""The ``loadtest`` seed profile: exactly 5,000 catalog items, 50 users, 12 teams,
20 zones, 200 lists and 60 dashboards, generated purely from the index (no RNG) so re-running
:func:`build` always produces byte-identical data.

Every hostname/IP/CIDR is fictional: ``example.com``, RFC 5737 (unused here only because
5,000 hosts would exhaust its three /24s many times over -- see the IPv6 zones instead) and
RFC 3849 (``2001:db8::/32``) for zone CIDRs.

Scope distribution (by ``index % 10``, so every count below divides evenly): 60% GLOBAL,
30% TEAM, 10% PERSONAL, with ``team_ids``/``owner_usernames`` always populated for
TEAM/PERSONAL so nothing is generated as an accidental orphan (DATA_MODEL.md §5.1).
"""

from __future__ import annotations

from collections import defaultdict

from panic_common.models import (
    CatalogItem,
    Connection,
    Dashboard,
    DashboardWidget,
    EndpointList,
    PermissionFlag,
    Protocol,
    ScopeType,
    SecurityZone,
    SiteDefinition,
    SystemSettings,
    TeamDefinition,
    UserAccount,
    WidgetType,
)
from panic_server.fixtures import Fixture

N_SITES = 5
N_TEAMS = 12
N_ZONES = 20
N_USERS = 50
N_CATALOG = 5000
N_LISTS = 200
N_DASHBOARDS = 60

_PROTOCOLS = (Protocol.URL, Protocol.SSH, Protocol.RDP, Protocol.LOCAL_APP)
_PORTS = {Protocol.URL: 443, Protocol.SSH: 22, Protocol.RDP: 3389, Protocol.LOCAL_APP: None}


def _scope_bucket(i: int) -> ScopeType:
    r = i % 10
    if r < 6:
        return ScopeType.GLOBAL
    if r < 9:
        return ScopeType.TEAM
    return ScopeType.PERSONAL


def _sites() -> list[SiteDefinition]:
    return [
        SiteDefinition(
            id=f"site-loadtest-{i:02d}",
            code=f"LT{i}",
            name=f"Load Site {i:02d}",
            description=f"Deterministic load-test site {i}.",
        )
        for i in range(N_SITES)
    ]


def _teams() -> list[TeamDefinition]:
    return [
        TeamDefinition(
            id=f"team-loadtest-{i:02d}",
            code=f"LT{i:02d}",
            name=f"Load Team {i:02d}",
            description=f"Deterministic load-test team {i}.",
        )
        for i in range(N_TEAMS)
    ]


def _zones() -> list[SecurityZone]:
    return [
        SecurityZone(
            id=f"zone-loadtest-{i:02d}",
            name=f"Load Zone {i:02d}",
            description=f"Deterministic load-test zone {i} (RFC 3849).",
            priority=200 - i,
            cidrs=[f"2001:db8:{i:04x}::/48"],
        )
        for i in range(N_ZONES)
    ]


def _users(teams: list[TeamDefinition]) -> list[UserAccount]:
    users = []
    for i in range(N_USERS):
        if i == 0:
            permissions = [PermissionFlag.GLOBAL_ADMIN]
        elif 1 <= i <= 5:
            permissions = [PermissionFlag.CAN_ADD_GLOBAL]
        elif 6 <= i <= 10:
            permissions = [PermissionFlag.CAN_ADD_TEAM]
        else:
            permissions = []
        username = f"loaduser{i:03d}"
        users.append(
            UserAccount(
                id=f"user-loadtest-{i:03d}",
                username=username,
                display_name=f"Load User {i:03d}",
                default_remote_user=username,
                permissions=permissions,
                team_ids=[teams[i % N_TEAMS].id],
            )
        )
    return users


def _catalog(teams: list[TeamDefinition], users: list[UserAccount], sites: list[SiteDefinition]) -> list[CatalogItem]:
    items = []
    for i in range(N_CATALOG):
        protocol = _PROTOCOLS[i % len(_PROTOCOLS)]
        port = _PORTS[protocol]
        host = f"host{i:05d}.example.com"
        scope = _scope_bucket(i)
        team_ids: list[str] = []
        owner_usernames: list[str] = []
        if scope is ScopeType.TEAM:
            team_ids = [teams[i % N_TEAMS].id]
        elif scope is ScopeType.PERSONAL:
            owner_usernames = [users[i % N_USERS].username]
        items.append(
            CatalogItem(
                id=f"cat-loadtest-{i:05d}",
                title=f"Load Item {i:05d}",
                host=host,
                connections=[Connection(protocol=protocol, port=port)],
                site=sites[i % N_SITES].code,
                normalized_keys=[f"loadtest://host{i:05d}.example.com:{port or 0}#{i}"],
                scope=scope,
                team_ids=team_ids,
                owner_usernames=owner_usernames,
                created_by="system",
                updated_by="system",
            )
        )
    return items


def _pools_by_scope(
    docs: list[CatalogItem] | list[EndpointList],
) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    """Split ``docs`` (already scoped) into ``(global_ids, team_ids_by_team, ids_by_owner)``."""
    global_ids: list[str] = []
    by_team: dict[str, list[str]] = defaultdict(list)
    by_owner: dict[str, list[str]] = defaultdict(list)
    for doc in docs:
        if doc.scope is ScopeType.GLOBAL:
            global_ids.append(doc.id)
        elif doc.scope is ScopeType.TEAM:
            by_team[doc.team_ids[0]].append(doc.id)
        elif doc.scope is ScopeType.PERSONAL:
            by_owner[doc.owner_usernames[0]].append(doc.id)
    return global_ids, dict(by_team), dict(by_owner)


def _pick_n(pool: list[str], offset: int, n: int) -> list[str]:
    if not pool:
        return []
    n = min(n, len(pool))
    return [pool[(offset + k) % len(pool)] for k in range(n)]


def _lists(
    teams: list[TeamDefinition],
    users: list[UserAccount],
    catalog_global: list[str],
    catalog_by_team: dict[str, list[str]],
    catalog_by_owner: dict[str, list[str]],
) -> list[EndpointList]:
    out = []
    for i in range(N_LISTS):
        scope = _scope_bucket(i)
        team_ids: list[str] = []
        owner_usernames: list[str] = []
        if scope is ScopeType.GLOBAL:
            pool = catalog_global
        elif scope is ScopeType.TEAM:
            team = teams[i % N_TEAMS].id
            team_ids = [team]
            pool = catalog_by_team.get(team, [])
        else:
            owner = users[i % N_USERS].username
            owner_usernames = [owner]
            pool = catalog_by_owner.get(owner, [])
        out.append(
            EndpointList(
                id=f"list-loadtest-{i:03d}",
                title=f"Load List {i:03d}",
                scope=scope,
                team_ids=team_ids,
                owner_usernames=owner_usernames,
                item_ids=_pick_n(pool, i * 5, 5),
                created_by="system",
                updated_by="system",
            )
        )
    return out


def _dashboards(
    teams: list[TeamDefinition],
    users: list[UserAccount],
    catalog_global: list[str],
    catalog_by_team: dict[str, list[str]],
    catalog_by_owner: dict[str, list[str]],
    list_global: list[str],
    list_by_team: dict[str, list[str]],
    list_by_owner: dict[str, list[str]],
) -> list[Dashboard]:
    out = []
    for i in range(N_DASHBOARDS):
        scope = _scope_bucket(i)
        team_ids: list[str] = []
        owner_usernames: list[str] = []
        if scope is ScopeType.GLOBAL:
            catalog_pool, list_pool = catalog_global, list_global
        elif scope is ScopeType.TEAM:
            team = teams[i % N_TEAMS].id
            team_ids = [team]
            catalog_pool, list_pool = catalog_by_team.get(team, []), list_by_team.get(team, [])
        else:
            owner = users[i % N_USERS].username
            owner_usernames = [owner]
            catalog_pool, list_pool = catalog_by_owner.get(owner, []), list_by_owner.get(owner, [])

        dashboard_id = f"dash-loadtest-{i:03d}"
        widgets = []
        for w in range(3):
            widget_id = f"widget-loadtest-{i:03d}-{w}"
            use_list = w % 2 == 1 and bool(list_pool)
            if use_list:
                widgets.append(
                    DashboardWidget(
                        id=widget_id,
                        dashboard_id=dashboard_id,
                        widget_type=WidgetType.LIST,
                        grid_x=1 + w * 4,
                        list_id=_pick_n(list_pool, i + w, 1)[0],
                    )
                )
            else:
                widgets.append(
                    DashboardWidget(
                        id=widget_id,
                        dashboard_id=dashboard_id,
                        widget_type=WidgetType.HOST,
                        grid_x=1 + w * 4,
                        catalog_item_id=_pick_n(catalog_pool, i + w, 1)[0],
                    )
                )
        out.append(
            Dashboard(
                id=dashboard_id,
                title=f"Load Dashboard {i:03d}",
                scope=scope,
                team_ids=team_ids,
                owner_usernames=owner_usernames,
                sort_order=i,
                widgets=widgets,
                created_by="system",
                updated_by="system",
            )
        )
    return out


def build() -> Fixture:
    """Build the ``loadtest`` fixture. Pure, deterministic, no I/O."""
    sites = _sites()
    teams = _teams()
    zones = _zones()
    users = _users(teams)
    catalog = _catalog(teams, users, sites)

    catalog_global, catalog_by_team, catalog_by_owner = _pools_by_scope(catalog)
    lists_ = _lists(teams, users, catalog_global, catalog_by_team, catalog_by_owner)
    list_global, list_by_team, list_by_owner = _pools_by_scope(lists_)
    dashboards = _dashboards(
        teams, users, catalog_global, catalog_by_team, catalog_by_owner, list_global, list_by_team, list_by_owner
    )

    settings = SystemSettings(default_global_dashboard_id=dashboards[0].id, updated_by="system")

    return Fixture(
        sites=sites,
        teams=teams,
        zones=zones,
        users=users,
        catalog=catalog,
        lists=lists_,
        dashboards=dashboards,
        system_settings=settings,
    )

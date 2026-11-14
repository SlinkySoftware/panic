"""Canonical enterprise operations fixtures (``MockPortalStore``) and the process-wide ``STORE``.

Stage 1 served ``MockPortalStore`` directly; from Stage 2 ``STORE`` is a ``DatabasePortalStore``
(``panic_server.store_db``) which reuses this module's fixtures for seeding.

All hostnames, IPv4/IPv6 blocks, and labels are strictly vendor-agnostic and use
reserved documentation/private ranges (example.com / example.net / RFC 5737 / RFC 1918 / RFC 3849).
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from panic_server.store_db import DatabasePortalStore

from panic_common.hygiene import normalize_target, preview_catalog_submission
from panic_common.launchers import interpolate_local_app_command, interpolate_ssh_command
from panic_common.models import (
    AuditLogEntry,
    CatalogItem,
    Dashboard,
    DashboardWidget,
    DensityMode,
    EndpointList,
    PermissionFlag,
    Protocol,
    ScopeType,
    SecurityZone,
    SimulationState,
    SiteDefinition,
    SystemSettings,
    TeamDefinition,
    ThemeMode,
    UnreachablePolicy,
    UserAccount,
    WidgetType,
)
from panic_common.rbac import (
    can_use_view_as,
    filter_items_for_list,
    has_permission,
    is_visible_in_scope,
)
from panic_common.zones import check_item_reachability, resolve_ip_zone

DASH_GLOBAL_NETOPS_ID = "d4f1a001-58cc-4372-a567-0e02b2c3d401"
DASH_GLOBAL_NOC_ID = "d4f1a002-58cc-4372-a567-0e02b2c3d402"
DASH_TEAM_COMPUTE_ID = "d4f1a003-58cc-4372-a567-0e02b2c3d403"
DASH_TEAM_SECOPS_ID = "d4f1a004-58cc-4372-a567-0e02b2c3d404"
DASH_PERSONAL_BENCH_ID = "d4f1a005-58cc-4372-a567-0e02b2c3d405"

DASH_LEGACY_ALIASES: dict[str, str] = {
    "dash-global-netops": DASH_GLOBAL_NETOPS_ID,
    "dash-global-noc": DASH_GLOBAL_NOC_ID,
    "dash-team-compute": DASH_TEAM_COMPUTE_ID,
    "dash-team-secops": DASH_TEAM_SECOPS_ID,
    "dash-personal-bench": DASH_PERSONAL_BENCH_ID,
}


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class MockPortalStore:
    """Thread-safe in-memory Stage 1 state container with RBAC, Teams, Zones, Lists, Catalog, and Dashboards."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.sites: list[SiteDefinition] = [
                SiteDefinition(
                    id="site-2sya",
                    code="2SYA",
                    name="Sydney Core DC",
                    description="Primary Eastern Seaboard core routing & compute facility",
                ),
                SiteDefinition(
                    id="site-3mel",
                    code="3MEL",
                    name="Melbourne Metro DC",
                    description="Redundant Southern transit, IPAM, and virtualization hub",
                ),
                SiteDefinition(
                    id="site-4bne",
                    code="4BNE",
                    name="Brisbane Edge POP",
                    description="Northern peering and border transit POP",
                ),
                SiteDefinition(
                    id="site-1cbr",
                    code="1CBR",
                    name="Canberra Gov DC",
                    description="Dedicated sovereign management & out-of-band console facility",
                ),
            ]

            self.teams: list[TeamDefinition] = [
                TeamDefinition(
                    id="team-netops",
                    name="Network Engineering",
                    code="NETOPS",
                    description="Core routing, switching, peering, and DMZ transit infrastructure",
                    members=["joperator", "priya.nair", "alex.chen"],
                ),
                TeamDefinition(
                    id="team-secops",
                    name="Security Operations",
                    code="SECOPS",
                    description="Perimeter defense, DMZ bastions, SIEM, and audit compliance",
                    members=["joperator", "sam.reeves"],
                ),
                TeamDefinition(
                    id="team-compute",
                    name="Compute & Virtualization",
                    code="COMPUTE",
                    description="Hypervisor clusters, Windows/Linux servers, and storage arrays",
                    members=["joperator", "priya.nair"],
                ),
            ]

            self.users: list[UserAccount] = [
                UserAccount(
                    id="usr-admin",
                    username="joperator",
                    display_name="Jordan Operator (Global Admin)",
                    default_remote_user="joperator",
                    ssh_template="ssh {user}@{host} -p {port} {flags}",
                    permissions=[
                        PermissionFlag.GLOBAL_ADMIN,
                        PermissionFlag.CAN_ADD_GLOBAL,
                        PermissionFlag.CAN_ADD_TEAM,
                    ],
                    team_ids=["team-netops", "team-secops", "team-compute"],
                    pinned_dashboard_ids=[
                        DASH_GLOBAL_NETOPS_ID,
                        DASH_TEAM_COMPUTE_ID,
                        DASH_PERSONAL_BENCH_ID,
                    ],
                    default_dashboard_id=None,
                    density=DensityMode.COMFORT,
                    theme=ThemeMode.DARK,
                    unreachable_policy=UnreachablePolicy.DIM,
                ),
                UserAccount(
                    id="usr-global-contrib",
                    username="priya.nair",
                    display_name="Priya Nair (Global & Team Contributor)",
                    default_remote_user="pnair",
                    ssh_template="ssh {user}@{host} -p {port} {flags}",
                    permissions=[
                        PermissionFlag.CAN_ADD_GLOBAL,
                        PermissionFlag.CAN_ADD_TEAM,
                    ],
                    team_ids=["team-netops", "team-compute"],
                    pinned_dashboard_ids=[
                        DASH_GLOBAL_NETOPS_ID,
                        DASH_TEAM_COMPUTE_ID,
                    ],
                    default_dashboard_id=DASH_TEAM_COMPUTE_ID,
                ),
                UserAccount(
                    id="usr-team-lead",
                    username="sam.reeves",
                    display_name="Sam Reeves (Team Scope Contributor)",
                    default_remote_user="sreeves",
                    ssh_template="ssh {user}@{host} -p {port} {flags}",
                    permissions=[
                        PermissionFlag.CAN_ADD_TEAM,
                    ],
                    team_ids=["team-secops"],
                    pinned_dashboard_ids=[
                        DASH_GLOBAL_NETOPS_ID,
                        DASH_TEAM_SECOPS_ID,
                    ],
                    default_dashboard_id=DASH_TEAM_SECOPS_ID,
                ),
                UserAccount(
                    id="usr-standard",
                    username="alex.chen",
                    display_name="Alex Chen (Personal Scope Only)",
                    default_remote_user="achen",
                    ssh_template="ssh {user}@{host} -p {port} {flags}",
                    permissions=[],
                    team_ids=["team-netops"],
                    pinned_dashboard_ids=[
                        DASH_GLOBAL_NETOPS_ID,
                        DASH_PERSONAL_BENCH_ID,
                    ],
                    default_dashboard_id=None,
                ),
            ]

            self.system_settings = SystemSettings(
                default_global_dashboard_id=DASH_GLOBAL_NETOPS_ID,
                updated_by="joperator",
                updated_at="2026-11-01T00:00:00Z",
            )

            self.simulation = SimulationState(
                simulated_ip="10.10.50.14",
                override_zone_id=None,
                active_user_id="usr-admin",
                view_as_user_id=None,
            )

            self.zones: list[SecurityZone] = [
                SecurityZone(
                    id="zone-dmz",
                    name="DMZ",
                    description="Demilitarized perimeter & external transit segment",
                    priority=120,
                    cidrs=["10.20.100.0/24", "192.0.2.0/24", "2001:db8:20::/48"],
                    created_at="2026-10-15T08:00:00Z",
                ),
                SecurityZone(
                    id="zone-core",
                    name="Core Network",
                    description="Dedicated NetOps bastion subnet with routing & telemetry reachability",
                    priority=100,
                    cidrs=["10.10.50.0/24", "10.10.0.0/16", "2001:db8:10::/48"],
                    created_at="2026-10-15T08:05:00Z",
                ),
                SecurityZone(
                    id="zone-dc-mgmt",
                    name="DC Management",
                    description="Datacenter hypervisor, storage, and Out-of-Band management segment",
                    priority=90,
                    cidrs=["172.16.40.0/24", "172.16.0.0/16"],
                    created_at="2026-10-15T08:10:00Z",
                ),
                SecurityZone(
                    id="zone-corp",
                    name="Corporate LAN",
                    description="Standard campus & engineering VPN pool",
                    priority=50,
                    cidrs=["198.51.100.0/24", "203.0.113.0/24"],
                    created_at="2026-10-15T08:15:00Z",
                ),
            ]

            self.catalog: list[CatalogItem] = self._seed_catalog()
            self.lists: list[EndpointList] = self._seed_lists()
            self.dashboards: list[Dashboard] = self._seed_dashboards()
            self.audit_logs: list[AuditLogEntry] = self._seed_audit_logs()

    @property
    def auth_user(self) -> UserAccount:
        """Return the authenticated/primary session user (before any Admin 'View As' override)."""
        with self._lock:
            u = next((u for u in self.users if u.id == self.simulation.active_user_id), None)
            return u if u is not None else self.users[0]

    @property
    def active_user(self) -> UserAccount:
        """Return the effective user perspective (incorporating Admin 'View As' when active)."""
        with self._lock:
            auth = self.auth_user
            if can_use_view_as(auth) and self.simulation.view_as_user_id:
                target = next(
                    (u for u in self.users if u.id == self.simulation.view_as_user_id),
                    None,
                )
                if target is not None:
                    return target
            return auth

    def _seed_catalog(self) -> list[CatalogItem]:
        return [
            # GLOBAL scope items
            CatalogItem(
                id="cat-rtr-2sya-01",
                title="Core Router 01 (Sydney)",
                description="Primary MPLS/BGP core transit router",
                protocol=Protocol.SSH,
                host="router1.network.example.com",
                port=22,
                site="2SYA",
                path_or_args="-o StrictHostKeyChecking=accept-new",
                tags=["router", "bgp", "core"],
                normalized_key="ssh://router1.network.example.com:22",
                scope=ScopeType.GLOBAL,
                zone_ids=["zone-core", "zone-dmz"],
                created_by="joperator",
            ),
            CatalogItem(
                id="cat-rtr-3mel-02",
                title="Core Router 02 (Melbourne)",
                description="Redundant MPLS/BGP core transit router",
                protocol=Protocol.SSH,
                host="router2.network.example.com",
                port=22,
                site="3MEL",
                path_or_args="-o StrictHostKeyChecking=accept-new",
                tags=["router", "bgp", "core"],
                normalized_key="ssh://router2.network.example.com:22",
                scope=ScopeType.GLOBAL,
                zone_ids=["zone-core", "zone-dmz"],
                created_by="joperator",
            ),
            CatalogItem(
                id="cat-rtr-4bne-03",
                title="Edge Border Router 03 (Brisbane)",
                description="External peering border router",
                protocol=Protocol.SSH,
                host="border3.network.example.com",
                port=22,
                site="4BNE",
                tags=["router", "peering"],
                normalized_key="ssh://border3.network.example.com:22",
                scope=ScopeType.GLOBAL,
                zone_ids=["zone-dmz", "zone-core"],
                created_by="joperator",
            ),
            CatalogItem(
                id="cat-web-telemetry",
                title="Routing Telemetry Portal",
                description="Read-only BGP/IGP routing state visualizer and path trace",
                protocol=Protocol.WEB,
                host="https://telemetry.network.example.com/ui",
                port=443,
                site="2SYA",
                path_or_args="/ui",
                tags=["web", "telemetry"],
                normalized_key="web://telemetry.network.example.com:443/ui",
                scope=ScopeType.GLOBAL,
                zone_ids=[],  # All Zones
                created_by="joperator",
            ),
            CatalogItem(
                id="cat-web-ipam",
                title="Enterprise IPAM & DCIM",
                description="Global prefix, VLAN, rack, and site inventory",
                protocol=Protocol.WEB,
                host="https://ipam.ops.example.com",
                port=443,
                site="3MEL",
                tags=["web", "ipam"],
                normalized_key="web://ipam.ops.example.com:443",
                scope=ScopeType.GLOBAL,
                zone_ids=[],  # All Zones
                created_by="joperator",
            ),
            CatalogItem(
                id="cat-rdp-bastion-01",
                title="Operations Management Bastion",
                description="Standard Windows Server jump desktop",
                protocol=Protocol.RDP,
                host="bastion01.ops.example.com",
                port=3389,
                site="2SYA",
                account_override="OPS\\joperator",
                tags=["rdp", "bastion"],
                normalized_key="rdp://bastion01.ops.example.com:3389",
                scope=ScopeType.GLOBAL,
                zone_ids=["zone-core", "zone-dc-mgmt"],
                created_by="joperator",
            ),
            # TEAM scope items
            CatalogItem(
                id="cat-team-fw-dmz",
                title="DMZ Perimeter Firewall 01",
                description="High-assurance DMZ firewall CLI",
                protocol=Protocol.SSH,
                host="fw01.dmz.example.com",
                port=22,
                site="2SYA",
                tags=["firewall", "dmz"],
                normalized_key="ssh://fw01.dmz.example.com:22",
                scope=ScopeType.TEAM,
                team_ids=["team-netops", "team-secops"],
                zone_ids=["zone-dmz", "zone-core"],
                created_by="sam.reeves",
            ),
            CatalogItem(
                id="cat-team-pcap-app",
                title="Packet Capture Workbench",
                description="Local SOE thick-client packet analyzer",
                protocol=Protocol.LOCAL_APP,
                host="/opt/soe/bin/packet-workbench",
                port=None,
                site="2SYA",
                path_or_args="--profile dmz-tap-capture --user {user}",
                custom_uri="pktbench://launch?profile=dmz-tap-capture",
                tags=["local_app", "pcap"],
                normalized_key="local_app:///opt/soe/bin/packet-workbench --profile dmz-tap-capture --user {user}",
                scope=ScopeType.TEAM,
                team_ids=["team-netops", "team-secops"],
                zone_ids=["zone-core", "zone-dmz"],
                created_by="priya.nair",
            ),
            CatalogItem(
                id="cat-team-hv-web",
                title="Hypervisor Cluster Manager",
                description="Virtualization cluster control plane",
                protocol=Protocol.WEB,
                host="https://virtmgr.dc.example.com/ui",
                port=443,
                site="3MEL",
                path_or_args="/ui",
                tags=["compute", "virtualization"],
                normalized_key="web://virtmgr.dc.example.com:443/ui",
                scope=ScopeType.TEAM,
                team_ids=["team-compute"],
                zone_ids=["zone-dc-mgmt", "zone-core"],
                created_by="priya.nair",
            ),
            CatalogItem(
                id="cat-team-rdp-compute",
                title="Compute Admin Jump Host (RDP)",
                description="Cluster power tools RDP session",
                protocol=Protocol.RDP,
                host="win-compute01.dc.example.com",
                port=3389,
                site="3MEL",
                account_override="OPS\\joperator",
                tags=["rdp", "compute"],
                normalized_key="rdp://win-compute01.dc.example.com:3389",
                scope=ScopeType.TEAM,
                team_ids=["team-compute"],
                zone_ids=["zone-dc-mgmt", "zone-core"],
                created_by="priya.nair",
            ),
            # PERSONAL scope items
            CatalogItem(
                id="cat-pers-lab-rtr",
                title="Lab Test Router (Personal)",
                description="Personal staging lab router in 2SYA",
                protocol=Protocol.SSH,
                host="lab-rtr01.network.example.com",
                port=22,
                site="2SYA",
                tags=["lab", "personal"],
                normalized_key="ssh://lab-rtr01.network.example.com:22",
                scope=ScopeType.PERSONAL,
                owner_usernames=["joperator", "alex.chen"],
                zone_ids=["zone-core", "zone-dmz"],
                created_by="joperator",
            ),
            CatalogItem(
                id="cat-pers-console",
                title="Rack 14 Serial Console (Personal)",
                description="Personal OOB serial port for bench testing",
                protocol=Protocol.SSH,
                host="oob14.network.example.com",
                port=2222,
                site="1CBR",
                tags=["oob", "personal"],
                normalized_key="ssh://oob14.network.example.com:2222",
                scope=ScopeType.PERSONAL,
                owner_usernames=["joperator", "alex.chen"],
                zone_ids=["zone-core"],
                created_by="joperator",
            ),
        ]

    def _seed_lists(self) -> list[EndpointList]:
        return [
            EndpointList(
                id="list-global-routers",
                title="Routers",
                description="Global core and border routing fleet across all sites",
                scope=ScopeType.GLOBAL,
                item_ids=["cat-rtr-2sya-01", "cat-rtr-3mel-02", "cat-rtr-4bne-03"],
                created_by="joperator",
            ),
            EndpointList(
                id="list-global-portals",
                title="Operations Portals & Bastions",
                description="Global web portals and shared RDP bastions",
                scope=ScopeType.GLOBAL,
                item_ids=["cat-web-telemetry", "cat-web-ipam", "cat-rdp-bastion-01"],
                created_by="joperator",
            ),
            EndpointList(
                id="list-team-sec-net",
                title="DMZ & Packet Inspection Targets",
                description="Team-scoped firewall and packet capture tools (NetOps & SecOps)",
                scope=ScopeType.TEAM,
                team_ids=["team-netops", "team-secops"],
                item_ids=["cat-team-fw-dmz", "cat-team-pcap-app"],
                created_by="sam.reeves",
            ),
            EndpointList(
                id="list-team-compute",
                title="Virtualization & Compute Nodes",
                description="Team-scoped hypervisor and RDP administration endpoints",
                scope=ScopeType.TEAM,
                team_ids=["team-compute"],
                item_ids=["cat-team-hv-web", "cat-team-rdp-compute"],
                created_by="priya.nair",
            ),
            EndpointList(
                id="list-personal-lab",
                title="My Personal Lab Targets",
                description="Personal bench routers and serial consoles",
                scope=ScopeType.PERSONAL,
                owner_usernames=["joperator", "alex.chen"],
                item_ids=["cat-pers-lab-rtr", "cat-pers-console"],
                created_by="joperator",
            ),
        ]

    def resolve_dashboard_id(self, raw_id: str | None) -> str:
        """Normalize a dashboard UUID or legacy slug alias to its canonical UUID."""
        if not raw_id:
            return ""
        clean = str(raw_id).strip()
        return DASH_LEGACY_ALIASES.get(clean, clean)

    def resolve_default_dashboard(self, user: UserAccount | None = None) -> tuple[Dashboard | None, str]:
        """Resolve the effective Default Dashboard for a user:
        1. User's personal default_dashboard_id (if set and visible in scope)
        2. App-wide SystemSettings.default_global_dashboard_id (if visible in scope)
        3. First visible dashboard in sort order
        """
        with self._lock:
            target_user = user or self.active_user
            visible = [
                d
                for d in sorted(self.dashboards, key=lambda item: item.sort_order)
                if is_visible_in_scope(target_user, d.scope, d.team_ids, d.owner_usernames)
            ]
            visible_by_id = {d.id: d for d in visible}

            if target_user.default_dashboard_id:
                resolved_uid = self.resolve_dashboard_id(target_user.default_dashboard_id)
                if resolved_uid in visible_by_id:
                    return visible_by_id[resolved_uid], "USER"

            global_def_id = self.resolve_dashboard_id(self.system_settings.default_global_dashboard_id)
            if global_def_id in visible_by_id:
                return visible_by_id[global_def_id], "SYSTEM_GLOBAL"

            if visible:
                return visible[0], "FALLBACK"
            return None, "NONE"

    def _seed_dashboards(self) -> list[Dashboard]:
        return [
            Dashboard(
                id=DASH_GLOBAL_NETOPS_ID,
                title="Core Network Operations",
                description="Global operations launchpad featuring individual host cards and curated router lists",
                scope=ScopeType.GLOBAL,
                always_display=True,
                sort_order=1,
                created_by="joperator",
                widgets=[
                    DashboardWidget(
                        id="w-host-rtr1",
                        dashboard_id=DASH_GLOBAL_NETOPS_ID,
                        widget_type=WidgetType.HOST,
                        title="Core Router 01 (Sydney)",
                        grid_x=1,
                        grid_y=1,
                        grid_w=4,
                        grid_h=1,
                        catalog_item_id="cat-rtr-2sya-01",
                    ),
                    DashboardWidget(
                        id="w-host-fw1",
                        dashboard_id=DASH_GLOBAL_NETOPS_ID,
                        widget_type=WidgetType.HOST,
                        title="DMZ Perimeter Firewall 01",
                        grid_x=5,
                        grid_y=1,
                        grid_w=4,
                        grid_h=1,
                        catalog_item_id="cat-team-fw-dmz",
                    ),
                    DashboardWidget(
                        id="w-host-rdp1",
                        dashboard_id=DASH_GLOBAL_NETOPS_ID,
                        widget_type=WidgetType.HOST,
                        title="Operations Management Bastion",
                        grid_x=9,
                        grid_y=1,
                        grid_w=4,
                        grid_h=1,
                        catalog_item_id="cat-rdp-bastion-01",
                    ),
                    DashboardWidget(
                        id="w-list-routers",
                        dashboard_id=DASH_GLOBAL_NETOPS_ID,
                        widget_type=WidgetType.LIST,
                        title="Routers",
                        grid_x=1,
                        grid_y=2,
                        grid_w=12,
                        grid_h=1,
                        list_id="list-global-routers",
                    ),
                    DashboardWidget(
                        id="w-list-portals",
                        dashboard_id=DASH_GLOBAL_NETOPS_ID,
                        widget_type=WidgetType.LIST,
                        title="Operations Portals & Bastions",
                        grid_x=1,
                        grid_y=3,
                        grid_w=7,
                        grid_h=1,
                        list_id="list-global-portals",
                    ),
                    DashboardWidget(
                        id="w-list-personal",
                        dashboard_id=DASH_GLOBAL_NETOPS_ID,
                        widget_type=WidgetType.LIST,
                        title="My Personal Lab Targets",
                        grid_x=8,
                        grid_y=3,
                        grid_w=5,
                        grid_h=1,
                        list_id="list-personal-lab",
                    ),
                ],
            ),
            Dashboard(
                id=DASH_GLOBAL_NOC_ID,
                title="Global NOC & Peering Overview",
                description="Global edge routers, telemetry portals, and IPAM launchpad",
                scope=ScopeType.GLOBAL,
                sort_order=2,
                created_by="joperator",
                widgets=[
                    DashboardWidget(
                        id="w-noc-host1",
                        dashboard_id=DASH_GLOBAL_NOC_ID,
                        widget_type=WidgetType.HOST,
                        title="Edge Border Router 03 (Brisbane)",
                        grid_x=1,
                        grid_y=1,
                        grid_w=6,
                        grid_h=1,
                        catalog_item_id="cat-rtr-4bne-03",
                    ),
                    DashboardWidget(
                        id="w-noc-host2",
                        dashboard_id=DASH_GLOBAL_NOC_ID,
                        widget_type=WidgetType.HOST,
                        title="Routing Telemetry Portal",
                        grid_x=7,
                        grid_y=1,
                        grid_w=6,
                        grid_h=1,
                        catalog_item_id="cat-web-telemetry",
                    ),
                    DashboardWidget(
                        id="w-noc-list1",
                        dashboard_id=DASH_GLOBAL_NOC_ID,
                        widget_type=WidgetType.LIST,
                        title="Operations Portals & Bastions",
                        grid_x=1,
                        grid_y=2,
                        grid_w=12,
                        grid_h=1,
                        list_id="list-global-portals",
                    ),
                ],
            ),
            Dashboard(
                id=DASH_TEAM_COMPUTE_ID,
                title="Compute & Virtualization Team",
                description="Team-scoped launchpad for Compute & Virtualization engineers",
                scope=ScopeType.TEAM,
                team_ids=["team-compute"],
                sort_order=3,
                created_by="priya.nair",
                widgets=[
                    DashboardWidget(
                        id="w-comp-host1",
                        dashboard_id=DASH_TEAM_COMPUTE_ID,
                        widget_type=WidgetType.HOST,
                        title="Hypervisor Cluster Manager",
                        grid_x=1,
                        grid_y=1,
                        grid_w=6,
                        grid_h=1,
                        catalog_item_id="cat-team-hv-web",
                    ),
                    DashboardWidget(
                        id="w-comp-host2",
                        dashboard_id=DASH_TEAM_COMPUTE_ID,
                        widget_type=WidgetType.HOST,
                        title="Compute Admin Jump Host (RDP)",
                        grid_x=7,
                        grid_y=1,
                        grid_w=6,
                        grid_h=1,
                        catalog_item_id="cat-team-rdp-compute",
                    ),
                    DashboardWidget(
                        id="w-comp-list1",
                        dashboard_id=DASH_TEAM_COMPUTE_ID,
                        widget_type=WidgetType.LIST,
                        title="Virtualization & Compute Nodes",
                        grid_x=1,
                        grid_y=2,
                        grid_w=12,
                        grid_h=1,
                        list_id="list-team-compute",
                    ),
                ],
            ),
            Dashboard(
                id=DASH_TEAM_SECOPS_ID,
                title="SecOps & Perimeter Defense",
                description="Team-scoped launchpad for DMZ firewalls and packet capture appliances",
                scope=ScopeType.TEAM,
                team_ids=["team-secops", "team-netops"],
                sort_order=4,
                created_by="sam.reeves",
                widgets=[
                    DashboardWidget(
                        id="w-sec-host1",
                        dashboard_id=DASH_TEAM_SECOPS_ID,
                        widget_type=WidgetType.HOST,
                        title="DMZ Perimeter Firewall 01",
                        grid_x=1,
                        grid_y=1,
                        grid_w=6,
                        grid_h=1,
                        catalog_item_id="cat-team-fw-dmz",
                    ),
                    DashboardWidget(
                        id="w-sec-host2",
                        dashboard_id=DASH_TEAM_SECOPS_ID,
                        widget_type=WidgetType.HOST,
                        title="Packet Capture Workbench",
                        grid_x=7,
                        grid_y=1,
                        grid_w=6,
                        grid_h=1,
                        catalog_item_id="cat-team-pcap-app",
                    ),
                    DashboardWidget(
                        id="w-sec-list1",
                        dashboard_id=DASH_TEAM_SECOPS_ID,
                        widget_type=WidgetType.LIST,
                        title="DMZ & Packet Inspection Targets",
                        grid_x=1,
                        grid_y=2,
                        grid_w=12,
                        grid_h=1,
                        list_id="list-team-sec-net",
                    ),
                ],
            ),
            Dashboard(
                id=DASH_PERSONAL_BENCH_ID,
                title="Personal Bench Workspace",
                description="Individual operator workspace for lab routers and test endpoints",
                scope=ScopeType.PERSONAL,
                owner_usernames=["joperator", "alex.chen"],
                sort_order=5,
                created_by="joperator",
                widgets=[
                    DashboardWidget(
                        id="w-pers-host1",
                        dashboard_id=DASH_PERSONAL_BENCH_ID,
                        widget_type=WidgetType.HOST,
                        title="Lab Test Router (Personal)",
                        grid_x=1,
                        grid_y=1,
                        grid_w=6,
                        grid_h=1,
                        catalog_item_id="cat-pers-lab-rtr",
                    ),
                    DashboardWidget(
                        id="w-pers-list1",
                        dashboard_id=DASH_PERSONAL_BENCH_ID,
                        widget_type=WidgetType.LIST,
                        title="My Personal Lab Targets",
                        grid_x=1,
                        grid_y=2,
                        grid_w=12,
                        grid_h=1,
                        list_id="list-personal-lab",
                    ),
                ],
            ),
        ]

    def _seed_audit_logs(self) -> list[AuditLogEntry]:
        return [
            AuditLogEntry(
                id="aud-1004",
                actor_username="joperator",
                action="zone.cidr.update",
                target_type="security_zone",
                target_id="zone-dmz",
                summary="Linked CIDR 10.20.100.0/24 and 192.0.2.0/24 to DMZ zone",
                details={"cidrs": ["10.20.100.0/24", "192.0.2.0/24"]},
                created_at="2026-11-14T00:45:00Z",
            ),
            AuditLogEntry(
                id="aud-1003",
                actor_username="joperator",
                action="list.create",
                target_type="endpoint_list",
                target_id="list-global-routers",
                summary="Created Global list 'Routers' with 3 Global-scope items",
                details={"scope": "GLOBAL", "item_count": 3},
                created_at="2026-11-13T21:10:00Z",
            ),
            AuditLogEntry(
                id="aud-1002",
                actor_username="sam.reeves",
                action="catalog.create",
                target_type="catalog_item",
                target_id="cat-team-fw-dmz",
                summary="Added Team-scoped item 'DMZ Perimeter Firewall 01' (2SYA, Zone: DMZ)",
                details={"scope": "TEAM", "teams": ["team-netops", "team-secops"]},
                created_at="2026-11-13T18:22:00Z",
            ),
        ]

    def record_audit(
        self,
        action: str,
        target_type: str,
        target_id: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        with self._lock:
            entry = AuditLogEntry(
                id=f"aud-{uuid.uuid4().hex[:8]}",
                actor_username=self.active_user.username,
                action=action,
                target_type=target_type,
                target_id=target_id,
                summary=summary,
                details=details or {},
                created_at=_now_iso(),
            )
            self.audit_logs.insert(0, entry)
            return entry

    def _enrich_item(
        self,
        item: CatalogItem,
        active_zone: SecurityZone | None,
        zone_map: dict[str, SecurityZone],
        team_map: dict[str, TeamDefinition],
    ) -> dict[str, Any]:
        data = item.model_dump()
        user = self.active_user
        reach = check_item_reachability(item, active_zone)
        effective_user = item.account_override or user.default_remote_user
        normalized_key, clean_host, effective_port = normalize_target(
            item.protocol, item.host, item.port, item.path_or_args
        )

        zone_names = (
            [zone_map[zid].name for zid in item.zone_ids if zid in zone_map]
            if item.zone_ids
            else ["All Zones"]
        )
        team_names = [team_map[tid].name for tid in item.team_ids if tid in team_map]

        scope_label = "Global"
        if item.scope == ScopeType.TEAM:
            scope_label = f"Team ({', '.join(team_names)})" if team_names else "Team"
        elif item.scope == ScopeType.PERSONAL:
            scope_label = "Personal"

        ssh_cmd = ""
        ssh_uri = ""
        local_app_cmd = ""
        web_url = ""
        if item.protocol == Protocol.SSH:
            ssh_cmd = interpolate_ssh_command(
                user.ssh_template,
                clean_host,
                effective_port,
                effective_user,
                item.path_or_args,
            )
            ssh_uri = f"ssh://{effective_user}@{clean_host}:{effective_port}"
        elif item.protocol == Protocol.LOCAL_APP:
            cmd_tpl = (
                item.path_or_args
                if "{host}" in (item.path_or_args or "")
                else f"{item.host} {item.path_or_args}".strip()
            )
            local_app_cmd = interpolate_local_app_command(
                cmd_tpl or '"/opt/soe/bin/launcher" --user {user}',
                clean_host,
                effective_port,
                effective_user,
            )
        elif item.protocol == Protocol.WEB:
            web_url = item.host if item.host.startswith(("http://", "https://")) else f"https://{clean_host}"

        data["clean_host"] = clean_host
        data["effective_port"] = effective_port
        if item.protocol == Protocol.LOCAL_APP:
            data["host_port_display"] = local_app_cmd
        elif item.protocol == Protocol.WEB:
            data["host_port_display"] = web_url
        elif item.protocol == Protocol.RDP:
            data["host_port_display"] = f"{clean_host}:{effective_port}"
        else:
            data["host_port_display"] = (
                clean_host if effective_port == 22 else f"{clean_host}:{effective_port}"
            )
        data["effective_user"] = effective_user
        data["normalized_key"] = normalized_key
        data["zone_names"] = zone_names
        data["zones_display"] = ", ".join(zone_names)
        data["team_names"] = team_names
        data["scope_display"] = (
            "Global"
            if item.scope == ScopeType.GLOBAL
            else ("Team" if item.scope == ScopeType.TEAM else "Personal")
        )
        data["scope_detail"] = scope_label
        data["reachability"] = reach.model_dump()
        data["launch"] = {
            "web_url": web_url,
            "ssh_command": ssh_cmd,
            "ssh_uri": ssh_uri,
            "rdp_download_url": f"/api/v1/launch/rdp/{item.id}.rdp",
            "local_app_command": local_app_cmd,
            "custom_uri": (
                item.custom_uri.replace("{host}", clean_host)
                .replace("{port}", str(effective_port))
                .replace("{user}", effective_user)
                if item.custom_uri
                else ""
            ),
        }
        return data

    def build_snapshot(self) -> dict[str, Any]:
        """Return a complete, enriched state payload for the UI and REST clients."""
        with self._lock:
            user = self.active_user
            zone_res = resolve_ip_zone(self.simulation.simulated_ip, self.zones)
            active_zone = zone_res.winning_zone
            if self.simulation.override_zone_id:
                override = next((z for z in self.zones if z.id == self.simulation.override_zone_id), None)
                if override is not None:
                    active_zone = override

            zone_map = {z.id: z for z in self.zones}
            team_map = {t.id: t for t in self.teams}

            visible_catalog_objs = [
                c
                for c in self.catalog
                if is_visible_in_scope(user, c.scope, c.team_ids, c.owner_usernames)
            ]
            enriched_catalog = [
                self._enrich_item(c, active_zone, zone_map, team_map) for c in visible_catalog_objs
            ]
            enriched_by_id = {c["id"]: c for c in enriched_catalog}

            enriched_lists: list[dict[str, Any]] = []
            for lst in self.lists:
                if not is_visible_in_scope(user, lst.scope, lst.team_ids, lst.owner_usernames):
                    continue
                l_dict = lst.model_dump()
                resolved_objs = filter_items_for_list(lst, visible_catalog_objs)
                l_dict["items"] = [enriched_by_id[c.id] for c in resolved_objs if c.id in enriched_by_id]
                l_dict["team_names"] = [team_map[tid].name for tid in lst.team_ids if tid in team_map]
                l_dict["scope_display"] = (
                    "Global"
                    if lst.scope == ScopeType.GLOBAL
                    else ("Team" if lst.scope == ScopeType.TEAM else "Personal")
                )
                enriched_lists.append(l_dict)

            list_by_id = {l_item["id"]: l_item for l_item in enriched_lists}

            default_dash, default_source = self.resolve_default_dashboard(user)
            effective_default_id = default_dash.id if default_dash else None
            global_default_id = self.resolve_dashboard_id(
                self.system_settings.default_global_dashboard_id
            )
            user_default_id = (
                self.resolve_dashboard_id(user.default_dashboard_id)
                if user.default_dashboard_id
                else None
            )

            all_visible_dashboards: list[dict[str, Any]] = []
            pinned_set = {self.resolve_dashboard_id(pid) for pid in user.pinned_dashboard_ids}
            for dash in sorted(self.dashboards, key=lambda d: d.sort_order):
                if not is_visible_in_scope(user, dash.scope, dash.team_ids, dash.owner_usernames):
                    continue
                d_dict = dash.model_dump()
                d_dict["url"] = f"/dashboard/{dash.id}"
                d_dict["edit_url"] = f"/dashboard/{dash.id}/edit"
                d_dict["team_names"] = [team_map[tid].name for tid in dash.team_ids if tid in team_map]
                d_dict["scope_display"] = (
                    "Global"
                    if dash.scope == ScopeType.GLOBAL
                    else ("Team" if dash.scope == ScopeType.TEAM else "Personal")
                )
                is_user_def = bool(user_default_id and dash.id == user_default_id)
                is_global_def = bool(global_default_id and dash.id == global_default_id)
                is_eff_def = bool(effective_default_id and dash.id == effective_default_id)
                d_dict["is_user_default"] = is_user_def
                d_dict["is_global_default"] = is_global_def
                d_dict["is_effective_default"] = is_eff_def
                d_dict["in_user_menu"] = (
                    True
                    if (
                        (dash.always_display and dash.scope in {ScopeType.GLOBAL, ScopeType.TEAM})
                        or is_global_def
                        or is_user_def
                    )
                    else ((dash.id in pinned_set) if pinned_set else True)
                )
                widgets_out: list[dict[str, Any]] = []
                for w in dash.widgets:
                    w_dict = w.model_dump()
                    w_dict["host_item"] = (
                        enriched_by_id.get(w.catalog_item_id) if w.catalog_item_id else None
                    )
                    w_dict["resolved_list"] = list_by_id.get(w.list_id) if w.list_id else None
                    widgets_out.append(w_dict)
                d_dict["widgets"] = widgets_out
                all_visible_dashboards.append(d_dict)

            menu_dashboards = [d for d in all_visible_dashboards if d["in_user_menu"]]
            if not menu_dashboards and all_visible_dashboards:
                menu_dashboards = all_visible_dashboards

            available_shared_dashboards = [
                d for d in all_visible_dashboards if d["scope"] in {"GLOBAL", "TEAM"}
            ]

            global_default_dash = next(
                (d for d in self.dashboards if d.id == global_default_id), None
            )

            auth = self.auth_user
            is_viewing_as = (
                can_use_view_as(auth)
                and self.simulation.view_as_user_id is not None
                and auth.id != user.id
            )

            user_dict = user.model_dump()
            user_dict["default_dashboard_id"] = user_default_id
            user_dict["effective_default_dashboard_id"] = effective_default_id
            user_dict["effective_default_dashboard_title"] = (
                default_dash.title if default_dash else None
            )
            user_dict["effective_default_dashboard_url"] = (
                f"/dashboard/{effective_default_id}" if effective_default_id else "/dashboard"
            )
            user_dict["effective_default_dashboard_source"] = default_source
            user_dict["can_global_admin"] = has_permission(user, PermissionFlag.GLOBAL_ADMIN)
            user_dict["can_add_global"] = has_permission(user, PermissionFlag.CAN_ADD_GLOBAL)
            user_dict["can_add_team"] = has_permission(user, PermissionFlag.CAN_ADD_TEAM)

            auth_dict = auth.model_dump()
            auth_dict["can_global_admin"] = has_permission(auth, PermissionFlag.GLOBAL_ADMIN)
            auth_dict["can_view_as"] = can_use_view_as(auth)

            return {
                "user": user_dict,
                "auth_user": auth_dict,
                "system_settings": {
                    **self.system_settings.model_dump(),
                    "default_global_dashboard_id": global_default_id,
                    "default_global_dashboard_title": (
                        global_default_dash.title if global_default_dash else ""
                    ),
                    "default_global_dashboard_url": (
                        f"/dashboard/{global_default_id}" if global_default_id else "/dashboard"
                    ),
                },
                "view_as": {
                    "active": is_viewing_as,
                    "can_view_as": can_use_view_as(auth),
                    "auth_user": auth_dict,
                    "target_user": user_dict if is_viewing_as else None,
                },
                "users": [u.model_dump() for u in self.users],
                "sites": [s.model_dump() for s in self.sites],
                "teams": [t.model_dump() for t in self.teams],
                "simulation": {
                    **self.simulation.model_dump(),
                    "resolved_zone": active_zone.model_dump() if active_zone else None,
                    "ip_resolution": zone_res.model_dump(),
                },
                "zones": [z.model_dump() for z in sorted(self.zones, key=lambda z: -z.priority)],
                "catalog": enriched_catalog,
                "lists": enriched_lists,
                "dashboards": menu_dashboards,
                "accessible_dashboards": all_visible_dashboards,
                "available_dashboards": available_shared_dashboards,
                "audit_logs": [a.model_dump() for a in self.audit_logs[:100]],
            }

    def find_launch_target(self, target_id: str) -> tuple[str, int, str, str] | None:
        """Find (host, port, resolved_username, title) by catalog_item_id for .rdp stream."""
        with self._lock:
            user = self.active_user
            for cat in self.catalog:
                if cat.id == target_id:
                    _, clean_host, port = normalize_target(cat.protocol, cat.host, cat.port, cat.path_or_args)
                    username = cat.account_override or user.default_remote_user
                    return clean_host, port, username, cat.title
        return None

    def preview_share(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            protocol = Protocol(str(payload.get("protocol", "SSH")).upper())
            host = str(payload.get("host", ""))
            raw_port = payload.get("port")
            port = int(raw_port) if raw_port not in (None, "") else None
            path_or_args = str(payload.get("path_or_args", ""))
            account_override = str(payload.get("account_override", ""))
            custom_uri = str(payload.get("custom_uri", ""))

            res = preview_catalog_submission(
                protocol=protocol,
                host=host,
                port=port,
                path_or_args=path_or_args,
                account_override=account_override,
                custom_uri=custom_uri,
                existing_catalog=self.catalog,
            )
            return res.model_dump()


def _build_store() -> DatabasePortalStore:
    """Stage 2+: the process-wide store is relational (``DatabasePortalStore``)."""
    from panic_server.store_db import DatabasePortalStore

    return DatabasePortalStore()


if TYPE_CHECKING:
    STORE: DatabasePortalStore


def __getattr__(name: str) -> Any:
    # ``STORE`` is built lazily (PEP 562) so ``store_db`` -> ``state`` imports never cycle.
    if name == "STORE":
        store = _build_store()
        globals()["STORE"] = store
        return store
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""``./panic addexamples`` data: a realistic, deterministic multi-team dataset that cannot collide with
real data.

Every id starts ``example-``, usernames ``ex-`` (no passwords: they cannot sign in), site and team codes
``EX-``, list and dashboard titles ``Example: ``. Hostnames are under ``example.net`` and zone CIDRs are
documentation ranges (RFC 5737 / 3849), so example zones never match a real client address. ``delexamples``
removes exactly what has the prefix (``panic_server.management.commands.panic_examples``).

Contents: 5 sites, 5 teams, 4 zones, 20 users; network (25 routers, 15 firewalls + 2 managers, 20 switches),
compute (vCenter/vSphere, ESXi, NSX, vRA, SDDC Manager), security tools, shared apps, RDP jump servers,
local apps and personal lab hosts; per-team lists and dashboards.
"""

from __future__ import annotations

from panic_common.hygiene import normalize_connections
from panic_common.models import (
    AuthSource,
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
    TeamDefinition,
    UserAccount,
    WidgetType,
)
from panic_server.fixtures import Fixture

ID_PREFIX = "example-"
USER_PREFIX = "ex-"
CODE_PREFIX = "EX-"
TITLE_PREFIX = "Example: "
DOMAIN = "example.net"

SITES = [("SYD", "Sydney DC"), ("MEL", "Melbourne DC"), ("BNE", "Brisbane"), ("PER", "Perth"), ("ADL", "Adelaide")]
TEAMS = {
    "net": ("NETOPS", "Network Operations"),
    "cmp": ("COMPUTE", "Compute Platforms"),
    "sec": ("SECOPS", "Security Operations"),
    "app": ("APPS", "Application Support"),
    "sd": ("SERVICEDESK", "Service Desk"),
}
ZONES = {
    "jump": ("Jump Hosts", ["192.0.2.0/26"], "Admin jump hosts"),
    "noc": ("Network Operations Centre", ["192.0.2.64/26"], "NOC workstations"),
    "dc": ("Datacentre Management", ["198.51.100.0/24", "2001:db8:10::/48"], "Out-of-band management"),
    "corp": ("Corporate", ["203.0.113.0/24", "2001:db8:100::/48"], "Office network"),
}


def _id(kind: str, key: str) -> str:
    return f"{ID_PREFIX}{kind}-{key}".lower().replace("_", "-")


def _site(code: str) -> str:
    return CODE_PREFIX + code


def _fqdn(name: str, site: str) -> str:
    return f"{name}.{site.lower()}.{DOMAIN}"


def build() -> Fixture:
    sites = [
        SiteDefinition(id=_id("site", c), code=_site(c), name=f"{TITLE_PREFIX}{n}", description=f"Example site {n}.")
        for c, n in SITES
    ]
    teams = {
        k: TeamDefinition(id=_id("team", code), code=CODE_PREFIX + code, name=f"{TITLE_PREFIX}{name}")
        for k, (code, name) in TEAMS.items()
    }
    zones = {
        k: SecurityZone(id=_id("zone", k), name=f"{TITLE_PREFIX}{name}", description=desc, cidrs=cidrs)
        for k, (name, cidrs, desc) in ZONES.items()
    }

    # ------------------------------------------------------------------ users
    users: list[UserAccount] = []

    def user(name: str, display: str, team: str | None, perms: list[PermissionFlag] | None = None) -> str:
        username = USER_PREFIX + name
        users.append(
            UserAccount(
                id=_id("user", name),
                username=username,
                display_name=f"{TITLE_PREFIX}{display}",
                default_remote_user=username,
                auth_source=AuthSource.LDAP,
                permissions=perms or [],
                team_ids=[teams[team].id] if team else [],
            )
        )
        return username

    admin = user("admin", "Portal Admin", None, [PermissionFlag.GLOBAL_ADMIN])
    editor = user("editor", "Shared Catalog Editor", "app", [PermissionFlag.CAN_ADD_GLOBAL])
    team_people = {
        "net": ["Nadia Network Lead", "Ned Router", "Nora Switch", "Nick Firewall", "Nina WAN", "Noah NOC"],
        "cmp": ["Carla Compute Lead", "Chris vSphere", "Cody NSX", "Cara Automation"],
        "sec": ["Sam Security Lead", "Sia Analyst", "Seb Pentest"],
        "app": ["Abe Apps", "Ava Apps"],
        "sd": ["Sid Desk", "Sue Desk", "Stu Desk"],
    }
    people: dict[str, list[str]] = {}
    for team, names in team_people.items():
        people[team] = []
        for i, display in enumerate(names):
            lead = i == 0 and team in ("net", "cmp", "sec")
            people[team].append(
                user(f"{team}{i + 1:02d}", display, team, [PermissionFlag.CAN_ADD_TEAM] if lead else [])
            )

    def author(team: str | None, owner: str | None) -> str:
        return owner or (people[team][0] if team else admin)

    # ------------------------------------------------------------------ catalog
    items: list[CatalogItem] = []

    def item(
        key: str,
        title: str,
        protocol: Protocol | tuple[Protocol, ...],
        host: str,
        site: str,
        *,
        team: str | None = None,
        owner: str | None = None,
        zones_for: list[str] | None = None,
        tags: list[str] | None = None,
        desc: str = "",
        path: str = "",
    ) -> str:
        protocols = protocol if isinstance(protocol, tuple) else (protocol,)
        # ``path`` belongs to the first connection (the primary, or a lone local app's command).
        connections = [Connection(protocol=p, path_or_args=path if i == 0 else "") for i, p in enumerate(protocols)]
        nkeys, clean_host, connections = normalize_connections(host, connections)
        scope = ScopeType.PERSONAL if owner else ScopeType.TEAM if team else ScopeType.GLOBAL
        items.append(
            CatalogItem(
                id=_id("item", key),
                title=title,
                description=desc,
                host=clean_host,
                connections=connections,
                site=_site(site),
                tags=sorted({*(tags or []), "example"}),
                normalized_keys=nkeys,
                scope=scope,
                team_ids=[teams[team].id] if team and not owner else [],
                owner_usernames=[owner] if owner else [],
                zone_ids=[zones[z].id for z in zones_for or []],
                created_by=author(team, owner),
                updated_by=author(team, owner),
            )
        )
        return _id("item", key)

    # Network: 25 routers, 15 firewalls (+2 managers), 20 switches across 5 sites.
    net: dict[str, list[str]] = {
        "core-rtr": [],
        "wan-rtr": [],
        "edge-rtr": [],
        "fw": [],
        "core-sw": [],
        "access-sw": [],
    }
    by_site: dict[str, list[str]] = {c: [] for c, _ in SITES}
    for n, (site, _) in enumerate(SITES):
        vendor = "cisco" if n % 2 == 0 else "juniper"
        s = site.lower()
        for role, count in (("core-rtr", 2), ("wan-rtr", 2), ("edge-rtr", 1)):
            for i in range(1, count + 1):
                name = f"{s}-{role}-{i:02d}"
                iid = item(
                    name,
                    name,
                    Protocol.SSH,
                    _fqdn(name, site),
                    site,
                    team="net",
                    tags=["router", role.split("-")[0], vendor, s],
                    desc=f"{vendor.title()} {role}",
                )
                net[role].append(iid)
                by_site[site].append(iid)
        for name in (f"{s}-fw-01", f"{s}-fw-02", f"{s}-dmz-fw-01"):
            iid = item(
                name,
                name,
                (Protocol.SSH, Protocol.URL),
                _fqdn(name, site),
                site,
                team="net",
                zones_for=["noc", "jump"],
                tags=["firewall", "palo-alto" if n % 2 else "fortinet", s],
                desc="Firewall CLI and web UI",
            )
            net["fw"].append(iid)
            by_site[site].append(iid)
        for role in ("core-sw", "access-sw"):
            for i in (1, 2):
                name = f"{s}-{role}-{i:02d}"
                iid = item(
                    name,
                    name,
                    Protocol.SSH,
                    _fqdn(name, site),
                    site,
                    team="net",
                    tags=["switch", role.split("-")[0], vendor, s],
                )
                net[role].append(iid)
                by_site[site].append(iid)
    fw_mgr = [
        item(
            f"fw-manager-{s.lower()}",
            f"Firewall Manager ({s})",
            Protocol.URL,
            _fqdn("fw-manager", s),
            s,
            team="net",
            tags=["firewall", "manager"],
            desc="Central firewall policy manager",
        )
        for s in ("SYD", "MEL")
    ]

    # Compute: vCenter (vSphere), ESXi, NSX, vRA / Aria, SDDC Manager.
    vcenters = [
        item(
            f"vcsa-{s.lower()}",
            f"vCenter {s}",
            Protocol.URL,
            _fqdn("vcsa-01", s),
            s,
            team="cmp",
            path="/ui/",
            tags=["vsphere", "vcenter"],
            desc="vSphere Client",
        )
        for s in ("SYD", "MEL")
    ]
    vcenters.append(
        item(
            "vcsa-mgmt",
            "vCenter Management",
            Protocol.URL,
            _fqdn("vcsa-mgmt", "SYD"),
            "SYD",
            team="cmp",
            path="/ui/",
            tags=["vsphere", "vcenter", "management"],
        )
    )
    esxi = {
        s: [
            item(
                f"esx-{s.lower()}-{i:02d}",
                f"esx-{s.lower()}-{i:02d}",
                (Protocol.SSH, Protocol.URL),
                _fqdn(f"esx-{i:02d}", s),
                s,
                team="cmp",
                zones_for=["dc", "jump"],
                tags=["esxi", "vsphere", s.lower()],
            )
            for i in range(1, 9)
        ]
        for s in ("SYD", "MEL")
    }
    nsx = [
        item(
            f"nsx-mgr-{i:02d}",
            f"NSX Manager {i:02d}",
            Protocol.URL,
            _fqdn(f"nsx-mgr-{i:02d}", "SYD"),
            "SYD",
            team="cmp",
            tags=["nsx", "manager"],
        )
        for i in range(1, 4)
    ]
    for i in range(1, 5):
        s = "SYD" if i < 3 else "MEL"
        nsx.append(
            item(
                f"nsx-edge-{i:02d}",
                f"nsx-edge-{i:02d}",
                Protocol.SSH,
                _fqdn(f"nsx-edge-{i:02d}", s),
                s,
                team="cmp",
                tags=["nsx", "edge"],
            )
        )
    vra = [
        item(
            "vra-portal",
            "vRA / Aria Automation",
            Protocol.URL,
            _fqdn("vra", "SYD"),
            "SYD",
            team="cmp",
            tags=["vra", "aria", "automation"],
            desc="Self-service catalog",
        ),
        item(
            "vra-orchestrator",
            "Aria Orchestrator",
            Protocol.URL,
            _fqdn("vro", "SYD"),
            "SYD",
            team="cmp",
            tags=["vra", "aria", "orchestrator"],
        ),
        item(
            "sddc-manager",
            "SDDC Manager",
            Protocol.URL,
            _fqdn("sddc-manager", "SYD"),
            "SYD",
            team="cmp",
            tags=["vcf", "sddc"],
        ),
    ]

    # Security tools.
    sec = [
        item("siem", "SIEM", Protocol.URL, _fqdn("siem", "SYD"), "SYD", team="sec", tags=["siem", "logging"]),
        item(
            "vuln-scanner",
            "Vulnerability Scanner",
            Protocol.URL,
            _fqdn("vulnscan", "SYD"),
            "SYD",
            team="sec",
            tags=["scanner"],
        ),
        item("pam", "Privileged Access Manager", Protocol.URL, _fqdn("pam", "MEL"), "MEL", team="sec", tags=["pam"]),
        item("bastion-syd", "bastion-syd", Protocol.SSH, _fqdn("bastion", "SYD"), "SYD", team="sec", tags=["bastion"]),
        item("bastion-mel", "bastion-mel", Protocol.SSH, _fqdn("bastion", "MEL"), "MEL", team="sec", tags=["bastion"]),
    ]

    # Shared (GLOBAL): everyday web tools, RDP jump servers, local apps.
    apps = [
        item(key, title, Protocol.URL, _fqdn(host, "SYD"), "SYD", tags=tags)
        for key, title, host, tags in (
            ("itsm", "IT Service Management", "itsm", ["itsm", "tickets"]),
            ("monitoring", "Monitoring", "monitoring", ["monitoring"]),
            ("ipam", "IPAM / DCIM", "ipam", ["ipam"]),
            ("wiki", "Operations Wiki", "wiki", ["docs"]),
            ("git", "Git", "git", ["code"]),
            ("status", "Status Page", "status", ["monitoring"]),
        )
    ]
    jump = [
        item(
            f"jump-{s.lower()}-{i:02d}",
            f"Jump Server {s} {i:02d}",
            Protocol.RDP,
            _fqdn(f"jump-{i:02d}", s),
            s,
            tags=["jump", "windows"],
        )
        for s in ("SYD", "MEL")
        for i in (1, 2)
    ]
    local = [
        item(
            "serial-console",
            "Serial console (PuTTY)",
            Protocol.LOCAL_APP,
            "localhost",
            "SYD",
            path="putty.exe -serial COM1 -sercfg 9600,8,n,1,N",
            tags=["console"],
        ),
        item("wireshark", "Wireshark", Protocol.LOCAL_APP, "localhost", "SYD", path="wireshark.exe", tags=["tools"]),
    ]

    # Personal lab hosts.
    personal = {
        owner: [
            item(
                f"lab-{owner}-{i}",
                f"{owner} lab {i}",
                Protocol.SSH,
                f"lab-{owner}-{i}.lab.{DOMAIN}",
                "SYD",
                owner=owner,
                tags=["lab"],
            )
            for i in (1, 2, 3)
        ]
        for owner in (people["net"][1], people["net"][2], people["cmp"][1], people["sec"][2])
    }

    # ------------------------------------------------------------------ lists
    lists: list[EndpointList] = []

    def mk_list(key: str, title: str, ids: list[str], *, team: str | None = None, owner: str | None = None) -> str:
        scope = ScopeType.PERSONAL if owner else ScopeType.TEAM if team else ScopeType.GLOBAL
        lists.append(
            EndpointList(
                id=_id("list", key),
                title=f"{TITLE_PREFIX}{title}",
                scope=scope,
                team_ids=[teams[team].id] if team and not owner else [],
                owner_usernames=[owner] if owner else [],
                item_ids=ids,
                created_by=author(team, owner),
                updated_by=author(team, owner),
            )
        )
        return _id("list", key)

    lst = {
        "core-rtr": mk_list("core-routers", "Core routers", net["core-rtr"], team="net"),
        "wan-rtr": mk_list("wan-routers", "WAN routers", net["wan-rtr"], team="net"),
        "edge-rtr": mk_list("edge-routers", "Edge routers", net["edge-rtr"], team="net"),
        "fw": mk_list("firewalls", "Firewalls", net["fw"] + fw_mgr, team="net"),
        "core-sw": mk_list("core-switches", "Core switches", net["core-sw"], team="net"),
        "access-sw": mk_list("access-switches", "Access switches", net["access-sw"], team="net"),
        "vc": mk_list("vcenters", "vCenter servers", vcenters, team="cmp"),
        "esx-syd": mk_list("esxi-syd", "ESXi - Sydney cluster", esxi["SYD"], team="cmp"),
        "esx-mel": mk_list("esxi-mel", "ESXi - Melbourne cluster", esxi["MEL"], team="cmp"),
        "nsx": mk_list("nsx", "NSX", nsx, team="cmp"),
        "vra": mk_list("vra", "vRA / Aria", vra, team="cmp"),
        "sec": mk_list("security-tools", "Security tools", sec, team="sec"),
        "jump": mk_list("jump-servers", "Jump servers", jump),
        "apps": mk_list("everyday-tools", "Everyday tools", apps + local),
    }
    for site, _ in SITES:
        lst[f"site-{site}"] = mk_list(f"network-{site}", f"{site} network devices", by_site[site], team="net")
    for owner, ids in personal.items():
        lst[f"lab-{owner}"] = mk_list(f"lab-{owner}", f"{owner} lab", ids, owner=owner)

    # ------------------------------------------------------------------ dashboards
    dashboards: list[Dashboard] = []

    def mk_dash(
        key: str,
        title: str,
        icon: str,
        widgets: list[tuple[str, str, int, int]],
        *,
        team: str | None = None,
        owner: str | None = None,
        desc: str = "",
    ) -> str:
        """``widgets``: (HOST|LIST, target id, w, h), packed left-to-right into 12 columns."""
        did = _id("dash", key)
        out: list[DashboardWidget] = []
        x, y, row_h = 1, 1, 0
        for n, (kind, target, w, h) in enumerate(widgets):
            if x + w - 1 > 12:
                x, y, row_h = 1, y + row_h, 0
            out.append(
                DashboardWidget(
                    id=f"{did}-w{n + 1}",
                    dashboard_id=did,
                    widget_type=WidgetType(kind),
                    grid_x=x,
                    grid_y=y,
                    grid_w=w,
                    grid_h=h,
                    catalog_item_id=target if kind == "HOST" else None,
                    list_id=target if kind == "LIST" else None,
                )
            )
            x, row_h = x + w, max(row_h, h)
        scope = ScopeType.PERSONAL if owner else ScopeType.TEAM if team else ScopeType.GLOBAL
        dashboards.append(
            Dashboard(
                id=did,
                title=f"{TITLE_PREFIX}{title}",
                description=desc,
                scope=scope,
                icon=icon,
                team_ids=[teams[team].id] if team and not owner else [],
                owner_usernames=[owner] if owner else [],
                widgets=out,
                created_by=author(team, owner),
                updated_by=author(team, owner),
            )
        )
        return did

    dash = {
        "net": mk_dash(
            "network-ops",
            "Network Operations",
            "router",
            [
                ("LIST", lst["core-rtr"], 4, 4),
                ("LIST", lst["wan-rtr"], 4, 4),
                ("LIST", lst["fw"], 4, 4),
                ("LIST", lst["core-sw"], 6, 3),
                ("LIST", lst["access-sw"], 6, 3),
                ("HOST", fw_mgr[0], 4, 1),
                ("HOST", fw_mgr[1], 4, 1),
                ("HOST", apps[1], 4, 1),
            ],
            team="net",
            desc="Routers, firewalls and switches across all sites",
        ),
        "net-syd": mk_dash(
            "network-syd",
            "Network - Sydney",
            "location_on",
            [
                ("LIST", lst["site-SYD"], 8, 5),
                ("HOST", net["core-rtr"][0], 4, 1),
                ("HOST", net["fw"][0], 4, 1),
            ],
            team="net",
        ),
        "net-mel": mk_dash(
            "network-mel",
            "Network - Melbourne",
            "location_on",
            [
                ("LIST", lst["site-MEL"], 8, 5),
                ("HOST", net["core-rtr"][2], 4, 1),
                ("HOST", net["fw"][3], 4, 1),
            ],
            team="net",
        ),
        "cmp": mk_dash(
            "compute",
            "Compute Platforms",
            "dns",
            [
                ("LIST", lst["vc"], 4, 2),
                ("LIST", lst["nsx"], 4, 3),
                ("LIST", lst["vra"], 4, 2),
                ("LIST", lst["esx-syd"], 6, 4),
                ("LIST", lst["esx-mel"], 6, 4),
            ],
            team="cmp",
            desc="vSphere, NSX and Aria",
        ),
        "sec": mk_dash(
            "security",
            "Security Operations",
            "security",
            [
                ("LIST", lst["sec"], 6, 3),
                ("LIST", lst["fw"], 6, 4),
            ],
            team="sec",
        ),
        "sd": mk_dash(
            "service-desk",
            "Service Desk",
            "support_agent",
            [
                ("HOST", apps[0], 4, 1),
                ("HOST", apps[1], 4, 1),
                ("HOST", apps[5], 4, 1),
                ("LIST", lst["jump"], 6, 2),
                ("LIST", lst["apps"], 6, 3),
            ],
            desc="Everyday tools and jump servers for everyone",
        ),
    }
    lab_owner = people["net"][1]
    dash["lab"] = mk_dash("my-lab", "My Lab", "science", [("LIST", lst[f"lab-{lab_owner}"], 6, 2)], owner=lab_owner)

    # Team members get their team dashboard pinned and as default; everyone gets Service Desk pinned.
    team_dash = {"net": dash["net"], "cmp": dash["cmp"], "sec": dash["sec"], "app": dash["sd"], "sd": dash["sd"]}
    by_username = {u.username: u for u in users}
    for team, names in people.items():
        for uname in names:
            pins = [team_dash[team]] + ([dash["sd"]] if team_dash[team] != dash["sd"] else [])
            if team == "net":
                pins += [dash["net-syd"], dash["net-mel"]]
            if uname == lab_owner:
                pins.append(dash["lab"])
            by_username[uname].pinned_dashboard_ids = pins
            by_username[uname].default_dashboard_id = team_dash[team]
    for extra in (admin, editor):
        by_username[extra].pinned_dashboard_ids = [dash["sd"]]

    return Fixture(
        sites=sites,
        teams=list(teams.values()),
        zones=list(zones.values()),
        users=users,
        catalog=items,
        lists=lists,
        dashboards=dashboards,
        system_settings=None,  # never touches the app-wide default dashboard
    )

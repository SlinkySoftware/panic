"""Unit tests for panic_common: normalization, deduplication, credential hygiene, zones, RBAC, lists, launchers."""

from __future__ import annotations

from panic_common.hygiene import (
    check_credential_hygiene,
    normalize_target,
    preview_catalog_submission,
)
from panic_common.launchers import (
    generate_rdp_content,
    interpolate_local_app_command,
    interpolate_ssh_command,
    sanitize_launch_param,
)
from panic_common.models import (
    CatalogItem,
    PermissionFlag,
    Protocol,
    ScopeType,
    SecurityZone,
    UserAccount,
)
from panic_common.rbac import can_create_or_edit_scope, validate_list_item_scopes
from panic_common.zones import check_item_reachability, resolve_ip_zone


def test_normalize_target_resolves_defaults_and_strips_slashes() -> None:
    key, host, port = normalize_target(Protocol.WEB, "HTTPS://Portal.Ops.Example.Net/ui///", None, "")
    assert key == "web://portal.ops.example.net:443/ui"
    assert host == "portal.ops.example.net"
    assert port == 443

    ssh_key, ssh_host, ssh_port = normalize_target(Protocol.SSH, "Core-RTR-01.Ops.Example.Net", None, "-A")
    assert ssh_key == "ssh://core-rtr-01.ops.example.net:22"
    assert ssh_host == "core-rtr-01.ops.example.net"
    assert ssh_port == 22

    rdp_key, _, rdp_port = normalize_target(Protocol.RDP, "win-jump-01.ops.example.net:3390", None, "")
    assert rdp_key == "rdp://win-jump-01.ops.example.net:3390"
    assert rdp_port == 3390

    app_key, app_cmd, app_port = normalize_target(
        Protocol.LOCAL_APP,
        "/opt/soe/bin/packet-workbench",
        None,
        "--profile dmz-tap-capture",
    )
    assert app_key == "local_app:///opt/soe/bin/packet-workbench --profile dmz-tap-capture"
    assert app_cmd == "/opt/soe/bin/packet-workbench"
    assert app_port == 0


def test_credential_hygiene_rejects_embedded_passwords_and_flags() -> None:
    errs1 = check_credential_hygiene(Protocol.WEB, "https://admin:hunter2@portal.example.net/login")
    assert len(errs1) >= 1

    errs2 = check_credential_hygiene(Protocol.SSH, "rtr.example.net", path_or_args="-pw MySecret123")
    assert len(errs2) >= 1

    errs3 = check_credential_hygiene(Protocol.SSH, "rtr.example.net", account_override="admin:secret")
    assert len(errs3) >= 1

    clean = check_credential_hygiene(
        Protocol.SSH,
        "rtr.example.net",
        path_or_args="-o StrictHostKeyChecking=accept-new",
        account_override="netadmin",
    )
    assert clean == []


def test_deduplication_preview_detects_existing_item() -> None:
    existing = [
        CatalogItem(
            id="cat-1",
            title="Core Router 01",
            description="Primary core router",
            protocol=Protocol.SSH,
            host="core-rtr-01.ops.example.net",
            port=22,
            site="2SYA",
            normalized_key="ssh://core-rtr-01.ops.example.net:22",
        )
    ]
    preview = preview_catalog_submission(
        protocol=Protocol.SSH,
        host="CORE-RTR-01.ops.example.net:22",
        port=None,
        path_or_args="-A",
        account_override="netops",
        custom_uri="",
        existing_catalog=existing,
    )
    assert preview.hygiene_passed is True
    assert preview.duplicate_found is True
    assert preview.existing_item is not None
    assert preview.existing_item.id == "cat-1"


def test_zone_resolution_specificity_and_priority() -> None:
    zones = [
        SecurityZone(
            id="z-broad",
            name="Corporate Supernet",
            description="Broad /16",
            priority=50,
            cidrs=["10.10.0.0/16"],
        ),
        SecurityZone(
            id="z-specific",
            name="DMZ",
            description="Specific /24",
            priority=100,
            cidrs=["10.10.50.0/24"],
        ),
    ]
    res = resolve_ip_zone("10.10.50.14", zones)
    assert res.valid_ip is True
    assert res.winning_zone is not None
    assert res.winning_zone.id == "z-specific"
    assert len(res.candidates) == 2

    item = CatalogItem(
        id="cat-dmz",
        title="DMZ Bastion",
        protocol=Protocol.SSH,
        host="bastion.dmz.example.net",
        port=22,
        site="2SYA",
        normalized_key="ssh://bastion.dmz.example.net:22",
        zone_ids=["z-specific"],
    )
    assert check_item_reachability(item, res.winning_zone).reachable is True
    assert check_item_reachability(item, zones[0]).reachable is False


def test_rbac_permissions_and_list_scope_matching() -> None:
    std_user = UserAccount(
        id="u-std",
        username="alex",
        display_name="Alex Operator",
        default_remote_user="alex",
        permissions=[],
    )
    team_user = UserAccount(
        id="u-team",
        username="priya",
        display_name="Priya Lead",
        default_remote_user="priya",
        permissions=[PermissionFlag.CAN_ADD_TEAM],
    )
    admin_user = UserAccount(
        id="u-admin",
        username="joperator",
        display_name="Jordan Admin",
        default_remote_user="joperator",
        permissions=[PermissionFlag.GLOBAL_ADMIN],
    )

    assert can_create_or_edit_scope(std_user, ScopeType.PERSONAL)[0] is True
    assert can_create_or_edit_scope(std_user, ScopeType.TEAM)[0] is False
    assert can_create_or_edit_scope(std_user, ScopeType.GLOBAL)[0] is False

    assert can_create_or_edit_scope(team_user, ScopeType.TEAM)[0] is True
    assert can_create_or_edit_scope(team_user, ScopeType.GLOBAL)[0] is False

    assert can_create_or_edit_scope(admin_user, ScopeType.GLOBAL)[0] is True
    assert can_create_or_edit_scope(admin_user, ScopeType.TEAM)[0] is True

    catalog = [
        CatalogItem(
            id="c-global",
            title="Global Router",
            protocol=Protocol.SSH,
            host="r1.example.net",
            port=22,
            normalized_key="ssh://r1.example.net:22",
            scope=ScopeType.GLOBAL,
        ),
        CatalogItem(
            id="c-personal",
            title="Personal Router",
            protocol=Protocol.SSH,
            host="r2.example.net",
            port=22,
            normalized_key="ssh://r2.example.net:22",
            scope=ScopeType.PERSONAL,
        ),
    ]
    ok, errs = validate_list_item_scopes(ScopeType.GLOBAL, ["c-global"], catalog)
    assert ok is True
    assert errs == []

    bad_ok, bad_errs = validate_list_item_scopes(ScopeType.GLOBAL, ["c-global", "c-personal"], catalog)
    assert bad_ok is False
    assert len(bad_errs) == 1


def test_launchers_sanitize_injection_and_generate_rdp() -> None:
    malicious_host = "rtr.example.net\r\nalternate shell:s:cmd.exe"
    assert "\r" not in sanitize_launch_param(malicious_host)
    assert "\n" not in sanitize_launch_param(malicious_host)

    ssh_cmd = interpolate_ssh_command(
        "ssh {user}@{host} -p {port} {flags}",
        "core-sw-01.ops.example.net",
        22,
        "joperator",
        "-A",
    )
    assert ssh_cmd == "ssh joperator@core-sw-01.ops.example.net -p 22 -A"

    app_cmd = interpolate_local_app_command(
        '"/opt/soe/bin/fabric-console" --target {host}:{port} --user {user}',
        "fabric.ops.example.net",
        8443,
        "joperator",
    )
    assert app_cmd == '"/opt/soe/bin/fabric-console" --target fabric.ops.example.net:8443 --user joperator'

    rdp_body = generate_rdp_content(
        host=malicious_host,
        port=3389,
        username="OPS\\joperator",
        title="Jump Host 01",
    )
    assert "full address:s:rtr.example.netalternate shell:s:cmd.exe:3389\r\n" in rdp_body
    assert "username:s:OPS\\joperator\r\n" in rdp_body

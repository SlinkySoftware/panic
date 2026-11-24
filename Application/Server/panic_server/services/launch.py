"""``ItemView`` composition and the ``.rdp`` download flow (API.md §4.2/§4.3, closes F3).

Pure composition: every function here takes already-fetched ``panic_common.models`` instances
(or a ``Database`` handle for the one function that needs to fetch/audit) and returns plain
dicts/bytes. ``build_item_view`` is the single place "what does this catalog item look like, and
how do I launch it" is computed, reused by the dashboard view, search and the catalog
and list views -- never duplicated.

**Launch field decisions (not specified verbatim in API.md, made here):**
Each of an item's ``connections`` gets its own launch, computed from the shared host/account
plus that connection's ``port``/``path_or_args``/``custom_uri``:

- URL ``url``: ``custom_uri`` if set, else ``https://{host}[:port]{path_or_args}`` (port omitted
  when 443, the URL default).
- SSH ``command``/``uri``: ``panic_common.launchers.interpolate_ssh_command`` with the caller's
  own ``ssh_template``; ``path_or_args`` supplies ``{flags}``; the remote user is
  ``item.account_override`` if set, else the caller's ``default_remote_user``.
- LOCAL_APP ``command``: the connection's ``path_or_args`` is the local-app command *template*
  (there is no other field for it); interpolated the same way as SSH. ``custom_uri`` (if set) is
  surfaced as the optional ``uri``.
- RDP is always ``DOWNLOAD`` with ``href=/api/v1/launch/rdp/{id}.rdp``; the remote user embedded
  in the generated file is resolved identically to SSH/LOCAL_APP (``account_override`` else the
  caller's default), with ``?user=`` overriding at download time.
"""

from __future__ import annotations

import re
from typing import Any

from panic_common.launchers import (
    generate_rdp_content,
    interpolate_local_app_command,
    interpolate_ssh_command,
    sanitize_launch_param,
)
from panic_common.models import CatalogItem, Connection, Protocol, SecurityZone, UnreachablePolicy, UserAccount
from panic_common.visibility import matches, visibility_spec
from panic_common.zones import check_item_reachability
from panic_server.paths import app_path
from panic_server.store.client import get_db
from panic_server.store.errors import NotFound
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import settings as settings_repo

_FILENAME_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _target(item: CatalogItem, conn: Connection) -> str:
    return f"{item.host}:{conn.port}" if conn.port else item.host


def _remote_user(item: CatalogItem, caller: UserAccount) -> str:
    return sanitize_launch_param(item.account_override or caller.default_remote_user)


def _url(item: CatalogItem, conn: Connection) -> str:
    if conn.custom_uri:
        return conn.custom_uri
    port_part = "" if not conn.port or conn.port == 443 else f":{conn.port}"
    path = conn.path_or_args
    if path and not path.startswith("/"):
        path = f"/{path}"
    return f"https://{item.host}{port_part}{path}"


def _ssh_launch(item: CatalogItem, conn: Connection, caller: UserAccount) -> dict[str, Any]:
    remote_user = _remote_user(item, caller)
    command = interpolate_ssh_command(caller.ssh_template, item.host, conn.port, remote_user, conn.path_or_args)
    launch: dict[str, Any] = {"kind": "COPY", "command": command}
    scheme = settings_repo.ssh_uri_scheme(get_db())  # None when the admin turned the handler off
    if scheme:
        launch["uri"] = f"{scheme}://{remote_user}@{item.host}:{conn.port or 22}"
    return launch


def _local_app_launch(item: CatalogItem, conn: Connection, caller: UserAccount) -> dict[str, Any]:
    remote_user = _remote_user(item, caller)
    command = interpolate_local_app_command(conn.path_or_args, item.host, conn.port, remote_user)
    launch: dict[str, Any] = {"kind": "COPY", "command": command}
    if conn.custom_uri:
        launch["uri"] = sanitize_launch_param(conn.custom_uri)
    return launch


def _rdp_launch(item: CatalogItem) -> dict[str, Any]:
    return {"kind": "DOWNLOAD", "href": app_path(f"/api/v1/launch/rdp/{item.id}.rdp")}


def _launch(item: CatalogItem, conn: Connection, caller: UserAccount) -> dict[str, Any]:
    if conn.protocol == Protocol.URL:
        launch: dict[str, Any] = {"kind": "OPEN", "url": _url(item, conn)}
    elif conn.protocol == Protocol.SSH:
        launch = _ssh_launch(item, conn, caller)
    elif conn.protocol == Protocol.LOCAL_APP:
        launch = _local_app_launch(item, conn, caller)
    else:
        launch = _rdp_launch(item)
    return launch


def build_item_view(
    item: CatalogItem,
    *,
    caller: UserAccount,
    active_zone: SecurityZone | None,
    zones_by_id: dict[str, SecurityZone],
) -> dict[str, Any]:
    """The shared ``ItemView`` shape (API.md §4.2), server-side-interpolated for ``caller``.

    ``protocol``/``target``/``launch`` describe the primary connection (the row click);
    ``alt_launches`` holds the item's other connections in launch order.
    """
    reach = check_item_reachability(item, active_zone)
    zone_names = sorted(zones_by_id[zid].name for zid in item.zone_ids if zid in zones_by_id)
    # Only the alternatives name their protocol/target: the primary's are the view's own (payload budget).
    alt_launches = [
        {"protocol": str(c.protocol), "target": _target(item, c), **_launch(item, c, caller)}
        for c in item.connections[1:]
    ]

    return {
        "id": item.id,
        "title": item.title,
        "protocol": str(item.primary.protocol),
        "protocols": [str(c.protocol) for c in item.connections],
        "target": _target(item, item.primary),
        "site": item.site,
        "scope": str(item.scope),
        "zone_names": zone_names,
        "tags": list(item.tags),
        "reachable": reach.reachable,
        "unreachable_reason": None if reach.reachable else reach.reason,
        "launch": _launch(item, item.primary, caller),
        "alt_launches": alt_launches,
    }


def _rdp_filename(item: CatalogItem) -> str:
    slug = _FILENAME_UNSAFE_RE.sub("-", f"{item.title}-{item.host}".lower()).strip("-") or item.id
    return f"{slug}.rdp"


def get_rdp_download(
    db: Any,
    *,
    item_id: str,
    caller: UserAccount,
    active_zone: SecurityZone | None,
    override_user: str | None,
    client_ip: str,
    actor_username: str,
    view_as_username: str | None,
    request_id: str | None,
) -> tuple[bytes, str]:
    """Visible + reachable (per the caller's ``unreachable_policy``) RDP item -> ``(.rdp bytes, filename)``.

    Raises :class:`panic_server.store.errors.NotFound` uniformly for "does not exist", "not
    visible to the caller" (AR-2.7: never a 403 for an invisible resource) and "visible but
    ``unreachable_policy=HIDE`` and currently unreachable" (the item would never even be shown as
    a link, so the download must not work either, F3).
    """
    item = catalog_repo.get_catalog_item(db, item_id)
    rdp = item.connection(Protocol.RDP)
    if rdp is None or not matches(visibility_spec(caller), item):
        raise NotFound(catalog_repo.COLLECTION, item_id)

    reach = check_item_reachability(item, active_zone)
    if caller.unreachable_policy == UnreachablePolicy.HIDE and not reach.reachable:
        raise NotFound(catalog_repo.COLLECTION, item_id)

    remote_user = sanitize_launch_param(override_user) if override_user else _remote_user(item, caller)
    content = generate_rdp_content(host=item.host, port=rdp.port, username=remote_user, title=item.title)

    audit_repo.append_audit(
        db,
        actor_username=actor_username,
        action="launch.rdp.download",
        target_type="catalog_item",
        target_id=item.id,
        summary=f"{actor_username} downloaded .rdp for {item.title} ({item.host}:{rdp.port or 3389})",
        client_ip=client_ip,
        details={"host": item.host, "port": rdp.port, "username": remote_user},
        view_as_username=view_as_username,
        zone_id=active_zone.id if active_zone else None,
        request_id=request_id,
    )
    return content.encode("utf-8"), _rdp_filename(item)


__all__ = ["build_item_view", "get_rdp_download"]

"""``ItemView`` composition and the ``.rdp`` download flow (API.md §4.2/§4.3, closes F3).

Pure composition: every function here takes already-fetched ``panic_common.models`` instances
(or a ``Database`` handle for the one function that needs to fetch/audit) and returns plain
dicts/bytes. ``build_item_view`` is the single place "what does this catalog item look like, and
how do I launch it" is computed, reused by the dashboard view, search and (T-S6-07) the catalog
and list views -- never duplicated.

**Launch field decisions (not specified verbatim in API.md, made here):**
- WEB ``url``: ``custom_uri`` if set, else ``https://{host}[:port]{path_or_args}`` (port omitted
  when 443, the WEB default).
- SSH ``command``/``uri``: ``panic_common.launchers.interpolate_ssh_command`` with the caller's
  own ``ssh_template``; ``path_or_args`` supplies ``{flags}``; the remote user is
  ``item.account_override`` if set, else the caller's ``default_remote_user``.
- LOCAL_APP ``command``: ``item.path_or_args`` is the per-item local-app command *template*
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
from panic_common.models import CatalogItem, Protocol, SecurityZone, UnreachablePolicy, UserAccount
from panic_common.visibility import matches, visibility_spec
from panic_common.zones import check_item_reachability
from panic_server.store.errors import NotFound
from panic_server.store.repos import audit as audit_repo
from panic_server.store.repos import catalog as catalog_repo

_FILENAME_UNSAFE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _target(item: CatalogItem) -> str:
    return f"{item.host}:{item.port}" if item.port else item.host


def _remote_user(item: CatalogItem, caller: UserAccount) -> str:
    return sanitize_launch_param(item.account_override or caller.default_remote_user)


def _web_url(item: CatalogItem) -> str:
    if item.custom_uri:
        return item.custom_uri
    port_part = "" if not item.port or item.port == 443 else f":{item.port}"
    path = item.path_or_args
    if path and not path.startswith("/"):
        path = f"/{path}"
    return f"https://{item.host}{port_part}{path}"


def _ssh_launch(item: CatalogItem, caller: UserAccount) -> dict[str, Any]:
    remote_user = _remote_user(item, caller)
    command = interpolate_ssh_command(caller.ssh_template, item.host, item.port, remote_user, item.path_or_args)
    uri = f"ssh://{remote_user}@{item.host}:{item.port or 22}"
    return {"kind": "COPY", "command": command, "uri": uri}


def _local_app_launch(item: CatalogItem, caller: UserAccount) -> dict[str, Any]:
    remote_user = _remote_user(item, caller)
    command = interpolate_local_app_command(item.path_or_args, item.host, item.port, remote_user)
    launch: dict[str, Any] = {"kind": "COPY", "command": command}
    if item.custom_uri:
        launch["uri"] = sanitize_launch_param(item.custom_uri)
    return launch


def _rdp_launch(item: CatalogItem) -> dict[str, Any]:
    return {"kind": "DOWNLOAD", "href": f"/api/v1/launch/rdp/{item.id}.rdp"}


def build_item_view(
    item: CatalogItem,
    *,
    caller: UserAccount,
    active_zone: SecurityZone | None,
    zones_by_id: dict[str, SecurityZone],
) -> dict[str, Any]:
    """The shared ``ItemView`` shape (API.md §4.2), server-side-interpolated for ``caller``."""
    reach = check_item_reachability(item, active_zone)
    zone_names = sorted(zones_by_id[zid].name for zid in item.zone_ids if zid in zones_by_id)

    if item.protocol == Protocol.WEB:
        launch: dict[str, Any] = {"kind": "OPEN", "url": _web_url(item)}
    elif item.protocol == Protocol.SSH:
        launch = _ssh_launch(item, caller)
    elif item.protocol == Protocol.LOCAL_APP:
        launch = _local_app_launch(item, caller)
    else:
        launch = _rdp_launch(item)

    return {
        "id": item.id,
        "title": item.title,
        "protocol": str(item.protocol),
        "target": _target(item),
        "site": item.site,
        "scope": str(item.scope),
        "zone_names": zone_names,
        "tags": list(item.tags),
        "reachable": reach.reachable,
        "unreachable_reason": None if reach.reachable else reach.reason,
        "launch": launch,
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
    a link, so the download must not work either -- same behaviour the deleted Stage 1-5
    ``rdp_download_view``/``test_f3_rdp_download_requires_visibility`` enforced, F3).
    """
    item = catalog_repo.get_catalog_item(db, item_id)
    if item.protocol != Protocol.RDP or not matches(visibility_spec(caller), item):
        raise NotFound(catalog_repo.COLLECTION, item_id)

    reach = check_item_reachability(item, active_zone)
    if caller.unreachable_policy == UnreachablePolicy.HIDE and not reach.reachable:
        raise NotFound(catalog_repo.COLLECTION, item_id)

    remote_user = sanitize_launch_param(override_user) if override_user else _remote_user(item, caller)
    content = generate_rdp_content(host=item.host, port=item.port, username=remote_user, title=item.title)

    audit_repo.append_audit(
        db,
        actor_username=actor_username,
        action="launch.rdp.download",
        target_type="catalog_item",
        target_id=item.id,
        summary=f"{actor_username} downloaded .rdp for {item.title} ({item.host}:{item.port or 3389})",
        client_ip=client_ip,
        details={"host": item.host, "port": item.port, "username": remote_user},
        view_as_username=view_as_username,
        zone_id=active_zone.id if active_zone else None,
        request_id=request_id,
    )
    return content.encode("utf-8"), _rdp_filename(item)


__all__ = ["build_item_view", "get_rdp_download"]

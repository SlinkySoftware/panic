"""``./panic addexamples`` data: a re-keyed copy of the ``demo`` profile that cannot collide with real data.

Every id gets the ``example-`` prefix, usernames ``ex-``, site and team codes ``EX-``, titles ``Example: ``.
Example users have no password (they cannot sign in). Zones keep the demo's documentation-only CIDRs
(RFC 5737 / 3849), so they never match a real client address. ``delexamples`` removes exactly what has
the prefix (``panic_server.management.commands.panic_examples``).
"""

from __future__ import annotations

from typing import Any

from panic_server.fixtures import Fixture, demo

ID_PREFIX = "example-"
USER_PREFIX = "ex-"
CODE_PREFIX = "EX-"
TITLE_PREFIX = "Example: "


def _id(x: str) -> str:
    return x if x.startswith(ID_PREFIX) else ID_PREFIX + x


def _ids(xs: list[str]) -> list[str]:
    return [_id(x) for x in xs]


def _user(x: str) -> str:
    return x if x.startswith(USER_PREFIX) else USER_PREFIX + x


def _users(xs: list[str]) -> list[str]:
    return [_user(x) for x in xs]


def build() -> Fixture:
    src = demo.build()
    site_codes = {s.code: CODE_PREFIX + s.code for s in src.sites}

    def audit(m: Any) -> dict[str, str]:
        return {"created_by": _user(m.created_by), "updated_by": _user(m.updated_by)}

    def upd(model: Any, **changes: Any) -> Any:
        return model.model_copy(update=changes)

    return Fixture(
        sites=[upd(s, id=_id(s.id), code=site_codes[s.code], name=TITLE_PREFIX + s.name) for s in src.sites],
        teams=[upd(t, id=_id(t.id), code=CODE_PREFIX + t.code, name=TITLE_PREFIX + t.name) for t in src.teams],
        zones=[upd(z, id=_id(z.id), name=TITLE_PREFIX + z.name) for z in src.zones],
        users=[
            upd(
                u,
                id=_id(u.id),
                username=_user(u.username),
                display_name=TITLE_PREFIX + u.display_name,
                default_remote_user=_user(u.default_remote_user),
                team_ids=_ids(u.team_ids),
                pinned_dashboard_ids=_ids(u.pinned_dashboard_ids),
                default_dashboard_id=_id(u.default_dashboard_id) if u.default_dashboard_id else None,
                search_keys=[],
                **({"password_hash": None} if hasattr(u, "password_hash") else {}),
            )
            for u in src.users
        ],
        catalog=[
            upd(
                c,
                id=_id(c.id),
                site=site_codes.get(c.site, c.site),
                team_ids=_ids(c.team_ids),
                owner_usernames=_users(c.owner_usernames),
                zone_ids=_ids(c.zone_ids),
                tags=sorted({*c.tags, "example"}),
                search_keys=[],
                **audit(c),
            )
            for c in src.catalog
        ],
        lists=[
            upd(
                lst,
                id=_id(lst.id),
                title=TITLE_PREFIX + lst.title,
                team_ids=_ids(lst.team_ids),
                owner_usernames=_users(lst.owner_usernames),
                item_ids=_ids(lst.item_ids),
                search_keys=[],
                **audit(lst),
            )
            for lst in src.lists
        ],
        dashboards=[
            upd(
                d,
                id=_id(d.id),
                title=TITLE_PREFIX + d.title,
                team_ids=_ids(d.team_ids),
                owner_usernames=_users(d.owner_usernames),
                always_display=False,  # never forced into real users' menus
                widgets=[
                    upd(
                        w,
                        id=_id(w.id),
                        **({"dashboard_id": _id(w.dashboard_id)} if getattr(w, "dashboard_id", None) else {}),
                        **({"catalog_item_id": _id(w.catalog_item_id)} if w.catalog_item_id else {}),
                        **({"list_id": _id(w.list_id)} if w.list_id else {}),
                    )
                    for w in d.widgets
                ],
                search_keys=[],
                **audit(d),
            )
            for d in src.dashboards
        ],
        system_settings=None,  # never touches the app-wide default dashboard
    )

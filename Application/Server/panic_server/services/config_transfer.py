"""Config export and merge-import (super admin, Application Settings): sites, teams, zones, catalog
items and endpoint lists, personal ones included. Users, dashboards and settings are not config.

The file is ``format: panic-config``, ``schema_version: 1``. Import never deletes. Each record in
the file is matched to an existing one, first by id, then by a natural key:

- sites and teams by ``code``, zones by ``name``;
- catalog items and lists by title within their scope (PERSONAL: title + owners).

A matched record takes the file's values (``UPDATE``, listing the changed fields) unless nothing
differs; an unmatched one is added with the file's id (``ADD``). Keeping ids means a later import
of the same source (e.g. prod -> dev again) matches by id, renames included. A record whose key
matches two existing records, or that would take a code/name another record holds, or is invalid,
is skipped (``CONFLICT``). References (an item's teams/zones, a list's items) are translated to
the matched records' ids; ones that resolve to nothing are dropped with a warning.

:func:`plan_import` is the preview; :func:`apply_import` re-plans and refuses (409) when the plan
no longer matches the ``plan_digest`` the user confirmed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from django.conf import settings as django_settings
from pydantic import ValidationError

from panic_common.errors import ErrorCode
from panic_common.hygiene import check_connections, check_item_hygiene, normalize_connections
from panic_common.models import (
    CatalogItem,
    Connection,
    EndpointList,
    ScopeType,
    SecurityZone,
    SiteDefinition,
    TeamDefinition,
)
from panic_common.search_keys import search_keys as compute_search_keys
from panic_common.zones import validate_cidr_list
from panic_server import __version__
from panic_server.api.errors import ApiError
from panic_server.store.cas import iso_z, utcnow
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import lists as lists_repo
from panic_server.store.repos import sites as sites_repo
from panic_server.store.repos import teams as teams_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

CONFIG_FORMAT = "panic-config"
CONFIG_SCHEMA_VERSION = 1
SECTIONS = ("sites", "teams", "zones", "catalog", "lists")

#: Per section: the fields a config file carries (and import compares), besides ``id``.
FIELDS: dict[str, tuple[str, ...]] = {
    "sites": ("code", "name", "description"),
    "teams": ("code", "name", "description"),
    "zones": ("name", "description", "priority", "cidrs", "builtin"),
    "catalog": (
        "title",
        "description",
        "host",
        "connections",
        "site",
        "account_override",
        "tags",
        "scope",
        "team_ids",
        "owner_usernames",
        "zone_ids",
    ),
    "lists": ("title", "description", "scope", "team_ids", "owner_usernames", "item_ids"),
}


# ======================================================================== export


def _record(section: str, obj: Any) -> dict[str, Any]:
    dumped = obj.model_dump(mode="json")
    return {"id": dumped["id"], **{f: dumped[f] for f in FIELDS[section]}}


def export_config(db: Any) -> dict[str, Any]:
    """The whole config file; each section sorted by id so two exports of one state diff cleanly."""
    loaders: dict[str, Callable[[Any], list[Any]]] = {
        "sites": sites_repo.list_sites,
        "teams": teams_repo.list_teams,
        "zones": zones_repo.list_zones,
        "catalog": catalog_repo.list_all_catalog_items,
        "lists": lists_repo.list_all_lists,
    }
    doc: dict[str, Any] = {
        "format": CONFIG_FORMAT,
        "schema_version": CONFIG_SCHEMA_VERSION,
        "server_version": __version__,
        "exported_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for section, load in loaders.items():
        doc[section] = sorted((_record(section, o) for o in load(db)), key=lambda r: r["id"])
    return doc


# ======================================================================== plan


_VOLATILE = frozenset({"created_at", "updated_at"})


@dataclass
class _Op:
    section: str
    action: str  # ADD | UPDATE | UNCHANGED | CONFLICT
    source_id: str
    label: str
    target: Any = None  # the model to write (ADD/UPDATE)
    existing: Any = None
    fields: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class ImportPlan:
    ops: list[_Op]
    warnings: list[str]
    #: ``(old code, new code)`` site renames, applied to every catalog item's ``site``.
    site_renames: list[tuple[str, str]]

    @property
    def digest(self) -> str:
        # Timestamps are "now" for written records (``created_at`` too, on an ADD): leave them out, or a
        # preview's digest could never match the apply's.
        def stable(target: Any) -> Any:
            return (
                None
                if target is None
                else {k: v for k, v in target.model_dump(mode="json").items() if k not in _VOLATILE}
            )

        payload = [[o.section, o.action, o.source_id, stable(o.target), o.reason] for o in self.ops]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def summary(self) -> dict[str, dict[str, int]]:
        out = {s: {"added": 0, "changed": 0, "unchanged": 0, "conflicts": 0} for s in SECTIONS}
        key = {"ADD": "added", "UPDATE": "changed", "UNCHANGED": "unchanged", "CONFLICT": "conflicts"}
        for o in self.ops:
            out[o.section][key[o.action]] += 1
        return out

    def preview(self) -> dict[str, Any]:
        return {
            "plan_digest": self.digest,
            "summary": self.summary(),
            "changes": [
                {
                    "section": o.section,
                    "action": o.action,
                    "id": o.source_id,
                    "label": o.label,
                    **({"fields": o.fields} if o.action == "UPDATE" else {}),
                    **({"reason": o.reason} if o.action == "CONFLICT" else {}),
                }
                for o in self.ops
                if o.action != "UNCHANGED"
            ],
            "warnings": self.warnings,
        }


def _invalid(message: str) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, message, status_code=400)


def _parse(doc: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(doc, dict) or doc.get("format") != CONFIG_FORMAT:
        raise _invalid("Not a PANIC config export (format must be panic-config).")
    if doc.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise _invalid(f"Unsupported config schema_version {doc.get('schema_version')!r}.")
    out: dict[str, list[dict[str, Any]]] = {}
    for section in SECTIONS:
        records = doc.get(section, [])
        if not isinstance(records, list) or not all(isinstance(r, dict) and r.get("id") for r in records):
            raise _invalid(f"Section {section!r} must be a list of records that each have an id.")
        ids = [str(r["id"]) for r in records]
        if len(set(ids)) != len(ids):
            raise _invalid(f"Section {section!r} repeats an id.")
        out[section] = records
    return out


def _owners_key(owners: list[str]) -> tuple[str, ...]:
    return tuple(sorted(o.lower() for o in owners))


def _scoped_key(title: str, scope: str, owners: list[str]) -> tuple[Any, ...]:
    """Items and lists: title within scope; PERSONAL also by owners (two users may share a title)."""
    base: tuple[Any, ...] = (str(scope), title.strip().lower())
    return (*base, _owners_key(owners)) if str(scope) == ScopeType.PERSONAL else base


def _changed(existing: Any, target: Any, names: tuple[str, ...]) -> list[str]:
    a, b = existing.model_dump(mode="json"), target.model_dump(mode="json")
    return [n for n in names if a.get(n) != b.get(n)]


class _Planner:
    def __init__(self, db: Any, actor: str) -> None:
        self.db = db
        self.actor = actor
        self.now = iso_z(utcnow())
        self.ops: list[_Op] = []
        self.warnings: list[str] = []
        self.site_renames: list[tuple[str, str]] = []
        #: ``section -> file id -> target id`` for every record that will exist after import.
        self.id_map: dict[str, dict[str, str]] = {s: {} for s in SECTIONS}
        self.existing: dict[str, dict[str, Any]] = {}
        self.enabled_usernames: set[str] = set()

    # ---------------------------------------------------------------- matching

    def _match(
        self, section: str, rec: dict[str, Any], key_of: Any, claimed: set[str]
    ) -> tuple[Any | None, str | None]:
        """``(existing record or None, conflict reason or None)``: by id, then by natural key."""
        existing = self.existing[section]
        by_id = existing.get(str(rec["id"]))
        if by_id is not None:
            if by_id.id in claimed:
                return None, "another record in the file already matched the same existing record"
            return by_id, None
        key = key_of(rec)
        hits = [e for e in existing.values() if key_of(e.model_dump(mode="json")) == key]
        if len(hits) > 1:
            return None, f"{len(hits)} existing records match it; rename one so the match is unambiguous"
        if hits and hits[0].id in claimed:
            return None, "another record in the file already matched the same existing record"
        return (hits[0] if hits else None), None

    def _unique_clash(self, section: str, attr: str, value: str, own_id: str | None) -> bool:
        """Would ``attr=value`` collide with a different existing record (unique code / name)?"""
        return any(
            getattr(e, attr).lower() == value.lower() and e.id != own_id for e in self.existing[section].values()
        )

    def _map_refs(self, section: str, ids: list[str], what: str, label: str) -> list[str]:
        out: list[str] = []
        for i in ids:
            target = self.id_map[section].get(i) or (i if i in self.existing[section] else None)
            if target is None:
                self.warnings.append(f"{label}: dropped unknown {what} {i}")
            elif target not in out:
                out.append(target)
        return out

    def _add_op(self, section: str, rec: dict[str, Any], label: str, match: Any, target: Any) -> None:
        if match is None:
            self.ops.append(_Op(section, "ADD", str(rec["id"]), label, target=target))
            return
        changed = _changed(match, target, FIELDS[section])
        action = "UPDATE" if changed else "UNCHANGED"
        self.ops.append(
            _Op(
                section,
                action,
                str(rec["id"]),
                label,
                target=target if changed else None,
                existing=match,
                fields=changed,
            )
        )

    def _conflict(self, section: str, rec: dict[str, Any], label: str, reason: str) -> None:
        self.ops.append(_Op(section, "CONFLICT", str(rec["id"]), label, reason=reason))

    def _meta(self, match: Any) -> dict[str, Any]:
        """Version and audit fields for the written record: continue an existing one, else start fresh."""
        if match is None:
            return {"version": 1, "created_at": self.now, "updated_at": self.now}
        return {"version": match.version + 1, "created_at": match.created_at, "updated_at": self.now}

    # ---------------------------------------------------------------- sections

    def code_named(self, section: str, records: list[dict[str, Any]]) -> None:
        model = SiteDefinition if section == "sites" else TeamDefinition
        claimed: set[str] = set()
        for rec in records:
            code = str(rec.get("code", "")).strip().upper()
            label = code or str(rec["id"])
            if not code or not str(rec.get("name", "")).strip():
                self._conflict(section, rec, label, "code and name are required")
                continue
            match, reason = self._match(section, rec, lambda r: str(r.get("code", "")).strip().upper(), claimed)
            if reason:
                self._conflict(section, rec, label, reason)
                continue
            target_id = match.id if match is not None else str(rec["id"])
            if self._unique_clash(section, "code", code, target_id):
                self._conflict(section, rec, label, f"code {code} belongs to another existing record")
                continue
            target = model(
                id=target_id,
                code=code,
                name=str(rec["name"]).strip(),
                description=str(rec.get("description", "")),
                **self._meta(match),
            )
            if match is not None:
                claimed.add(match.id)
                if section == "sites" and match.code != code:
                    self.site_renames.append((match.code, code))
            self.id_map[section][str(rec["id"])] = target_id
            self._add_op(section, rec, label, match, target)

    def zones(self, records: list[dict[str, Any]]) -> None:
        claimed: set[str] = set()
        for rec in records:
            name = str(rec.get("name", "")).strip()
            label = name or str(rec["id"])
            match, reason = self._match("zones", rec, lambda r: str(r.get("name", "")).strip().lower(), claimed)
            if reason:
                self._conflict("zones", rec, label, reason)
                continue
            if match is not None and match.builtin:
                # The built-in Default zone: only its description is configurable.
                target = match.model_copy(update={"description": str(rec.get("description", "")), **self._meta(match)})
            else:
                try:
                    cidrs = validate_cidr_list([str(c) for c in rec.get("cidrs", [])])
                except ValueError as e:
                    self._conflict("zones", rec, label, f"invalid CIDR: {e}")
                    continue
                if not name:
                    self._conflict("zones", rec, label, "name is required")
                    continue
                target_id = match.id if match is not None else str(rec["id"])
                if self._unique_clash("zones", "name", name, target_id):
                    self._conflict("zones", rec, label, f"name {name} belongs to another existing zone")
                    continue
                target = SecurityZone(
                    id=target_id,
                    name=name,
                    description=str(rec.get("description", "")),
                    priority=int(rec.get("priority", 100)),
                    cidrs=cidrs,
                    builtin=False,
                    **self._meta(match),
                )
            if match is not None:
                claimed.add(match.id)
            self.id_map["zones"][str(rec["id"])] = target.id
            self._add_op("zones", rec, label, match, target)

    def _scope_fields(self, rec: dict[str, Any], label: str) -> tuple[str, list[str], list[str]]:
        scope = str(rec.get("scope", "GLOBAL"))
        team_ids = self._map_refs("teams", list(rec.get("team_ids", [])), "team", label)
        owners = [str(o) for o in rec.get("owner_usernames", [])]
        return scope, (team_ids if scope == ScopeType.TEAM else []), (owners if scope == ScopeType.PERSONAL else [])

    def _orphaned(self, scope: str, team_ids: list[str], owners: list[str]) -> bool:
        if scope == ScopeType.TEAM:
            return not team_ids
        if scope == ScopeType.PERSONAL:
            return not any(o in self.enabled_usernames for o in owners)
        return False

    def catalog(self, records: list[dict[str, Any]]) -> None:
        self.enabled_usernames = {u.username for u in users_repo.list_users(self.db, disabled=False)}
        known_sites = {s.code for s in self.existing["sites"].values()} | {
            o.target.code for o in self.ops if o.section == "sites" and o.target is not None
        }
        claimed: set[str] = set()

        def key_of(r: dict[str, Any]) -> tuple[Any, ...]:
            return _scoped_key(
                str(r.get("title", "")), str(r.get("scope", "GLOBAL")), list(r.get("owner_usernames", []))
            )

        for rec in records:
            title = str(rec.get("title", "")).strip()
            label = title or str(rec["id"])
            try:
                connections = [Connection.model_validate(c) for c in rec.get("connections", [])]
                scope_enum = ScopeType(str(rec.get("scope", "GLOBAL")))
            except (ValidationError, ValueError):
                self._conflict("catalog", rec, label, "invalid protocol or scope")
                continue
            host = str(rec.get("host", "")).strip()
            problems = check_connections(connections) + check_item_hygiene(
                host, str(rec.get("account_override", "")), connections
            )
            if not title or not host or problems:
                self._conflict("catalog", rec, label, "; ".join(problems) or "title and host are required")
                continue
            match, reason = self._match("catalog", rec, key_of, claimed)
            if reason:
                self._conflict("catalog", rec, label, reason)
                continue
            scope, team_ids, owners = self._scope_fields(rec, label)
            zone_ids = self._map_refs("zones", list(rec.get("zone_ids", [])), "zone", label)
            site = str(rec.get("site", ""))
            if site not in known_sites:
                self.warnings.append(f"{label}: site {site} does not exist")
            keys, clean_host, ordered = normalize_connections(host, connections)
            tags = [str(t) for t in rec.get("tags", [])]
            target = CatalogItem(
                id=match.id if match is not None else str(rec["id"]),
                title=title,
                description=str(rec.get("description", "")),
                host=clean_host,
                connections=ordered,
                site=site,
                account_override=str(rec.get("account_override", "")),
                tags=tags,
                normalized_keys=keys,
                scope=scope_enum,
                team_ids=team_ids,
                owner_usernames=owners,
                zone_ids=zone_ids,
                search_keys=compute_search_keys(title, clean_host, site, tags),
                orphaned=self._orphaned(scope, team_ids, owners),
                created_by=match.created_by if match is not None else self.actor,
                updated_by=self.actor,
                **self._meta(match),
            )
            if match is not None:
                claimed.add(match.id)
            self.id_map["catalog"][str(rec["id"])] = target.id
            self._add_op("catalog", rec, label, match, target)

    def lists(self, records: list[dict[str, Any]]) -> None:
        # Item scopes after import, to keep the same-scope rule (SCOPE_MISMATCH) for list members.
        item_scope = {i.id: str(i.scope) for i in self.existing["catalog"].values()}
        item_scope.update({o.target.id: str(o.target.scope) for o in self.ops if o.section == "catalog" and o.target})
        max_items = django_settings.PANIC_LIST_MAX_ITEMS
        claimed: set[str] = set()

        def key_of(r: dict[str, Any]) -> tuple[Any, ...]:
            return _scoped_key(
                str(r.get("title", "")), str(r.get("scope", "GLOBAL")), list(r.get("owner_usernames", []))
            )

        for rec in records:
            title = str(rec.get("title", "")).strip()
            label = title or str(rec["id"])
            try:
                scope_enum = ScopeType(str(rec.get("scope", "GLOBAL")))
            except ValueError:
                self._conflict("lists", rec, label, "invalid scope")
                continue
            if not title:
                self._conflict("lists", rec, label, "title is required")
                continue
            match, reason = self._match("lists", rec, key_of, claimed)
            if reason:
                self._conflict("lists", rec, label, reason)
                continue
            scope, team_ids, owners = self._scope_fields(rec, label)
            item_ids = []
            for iid in self._map_refs("catalog", list(rec.get("item_ids", [])), "item", label):
                if item_scope.get(iid) == scope:
                    item_ids.append(iid)
                else:
                    self.warnings.append(f"{label}: dropped item {iid} (not {scope} scope)")
            if len(item_ids) > max_items:
                self._conflict("lists", rec, label, f"more than {max_items} items")
                continue
            target = EndpointList(
                id=match.id if match is not None else str(rec["id"]),
                title=title,
                description=str(rec.get("description", "")),
                scope=scope_enum,
                team_ids=team_ids,
                owner_usernames=owners,
                item_ids=item_ids,
                search_keys=compute_search_keys(title, "", "", []),
                orphaned=self._orphaned(scope, team_ids, owners),
                created_by=match.created_by if match is not None else self.actor,
                updated_by=self.actor,
                **self._meta(match),
            )
            if match is not None:
                claimed.add(match.id)
            self.id_map["lists"][str(rec["id"])] = target.id
            self._add_op("lists", rec, label, match, target)


def plan_import(db: Any, doc: Any, actor: str) -> ImportPlan:
    records = _parse(doc)
    p = _Planner(db, actor)
    p.existing = {
        "sites": {s.id: s for s in sites_repo.list_sites(db)},
        "teams": {t.id: t for t in teams_repo.list_teams(db)},
        "zones": {z.id: z for z in zones_repo.list_zones(db)},
        "catalog": {i.id: i for i in catalog_repo.list_all_catalog_items(db)},
        "lists": {lst.id: lst for lst in lists_repo.list_all_lists(db)},
    }
    p.code_named("sites", records["sites"])
    p.code_named("teams", records["teams"])
    p.zones(records["zones"])
    p.catalog(records["catalog"])
    p.lists(records["lists"])
    return ImportPlan(ops=p.ops, warnings=p.warnings, site_renames=p.site_renames)


# ======================================================================== apply

_UPSERT: dict[str, Callable[[Any, Any], Any]] = {
    "sites": sites_repo.upsert_site,
    "teams": teams_repo.upsert_team,
    "zones": zones_repo.upsert_zone,
    "catalog": catalog_repo.upsert_catalog_item,
    "lists": lists_repo.upsert_list,
}


def apply_import(db: Any, doc: Any, plan_digest: str, actor: str) -> ImportPlan:
    """Write the plan if it is still the one previewed (``plan_digest``), else ``409 CONFLICT``."""
    plan = plan_import(db, doc, actor)
    if not plan_digest or plan.digest != plan_digest:
        raise ApiError(
            ErrorCode.VERSION_CONFLICT,
            "The data changed since the preview. Run the preview again and re-check the changes.",
            status_code=409,
        )
    for section in SECTIONS:  # sites before items, items before lists
        for op in plan.ops:
            if op.section == section and op.action in {"ADD", "UPDATE"}:
                _UPSERT[section](db, op.target)
        if section == "sites":
            for old, new in plan.site_renames:
                catalog_repo.rename_site_code(db, old, new)
    return plan


__all__ = ["CONFIG_FORMAT", "CONFIG_SCHEMA_VERSION", "ImportPlan", "apply_import", "export_config", "plan_import"]

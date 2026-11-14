"""Pure mapping of external identity-provider group/role claims to PANIC RBAC flags and Teams (T-S3-02).

No Django or network imports (AR-1.1). Group comparison is case-insensitive. LDAP distinguished
names are reduced to their first RDN value (``cn=netops,ou=groups,dc=example,dc=com`` -> ``netops``)
so either form may be configured.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from panic_common.models import PermissionFlag, TeamDefinition


@dataclass(frozen=True)
class ClaimMappingConfig:
    admin_groups: frozenset[str] = frozenset()
    global_contrib_groups: frozenset[str] = frozenset()
    team_contrib_groups: frozenset[str] = frozenset()
    # Explicit external group -> PANIC team code.
    team_group_map: Mapping[str, str] = field(default_factory=dict)
    # Groups named "<prefix><team code>" map to that team (e.g. "panic-team-netops" -> NETOPS).
    team_group_prefix: str = ""

    @classmethod
    def build(
        cls,
        admin_groups: Iterable[str] = (),
        global_contrib_groups: Iterable[str] = (),
        team_contrib_groups: Iterable[str] = (),
        team_group_map: Iterable[str] = (),
        team_group_prefix: str = "",
    ) -> ClaimMappingConfig:
        """Build from settings-style lists; ``team_group_map`` entries are ``"external-group=TEAMCODE"``."""
        pairs: dict[str, str] = {}
        for entry in team_group_map:
            group, sep, code = entry.partition("=")
            if sep and group.strip() and code.strip():
                pairs[normalize_group(group)] = code.strip().upper()
        return cls(
            admin_groups=frozenset(normalize_group(g) for g in admin_groups),
            global_contrib_groups=frozenset(normalize_group(g) for g in global_contrib_groups),
            team_contrib_groups=frozenset(normalize_group(g) for g in team_contrib_groups),
            team_group_map=pairs,
            team_group_prefix=team_group_prefix.strip().lower(),
        )


@dataclass(frozen=True)
class MappedIdentity:
    permissions: list[PermissionFlag]
    team_ids: list[str]


def normalize_group(group: str) -> str:
    """Lower-case a group name; reduce an LDAP DN to its leading RDN value."""
    g = group.strip()
    if "=" in g and "," in g:
        g = g.split(",", 1)[0].split("=", 1)[1]
    return g.strip().lower()


def map_claims(
    groups: Iterable[str],
    config: ClaimMappingConfig,
    teams: Iterable[TeamDefinition],
) -> MappedIdentity:
    """Return the PANIC permissions and team ids implied by ``groups``.

    ``GLOBAL_ADMIN`` implies both contributor flags. Unknown team codes are ignored.
    """
    normalized = {normalize_group(g) for g in groups if g and g.strip()}
    perms: list[PermissionFlag] = []
    if normalized & config.admin_groups:
        perms = [PermissionFlag.GLOBAL_ADMIN, PermissionFlag.CAN_ADD_GLOBAL, PermissionFlag.CAN_ADD_TEAM]
    else:
        if normalized & config.global_contrib_groups:
            perms.append(PermissionFlag.CAN_ADD_GLOBAL)
        if normalized & config.team_contrib_groups:
            perms.append(PermissionFlag.CAN_ADD_TEAM)

    by_code = {t.code.upper(): t.id for t in teams}
    team_ids: list[str] = []
    for g in sorted(normalized):
        code = config.team_group_map.get(g)
        if code is None and config.team_group_prefix and g.startswith(config.team_group_prefix):
            code = g[len(config.team_group_prefix) :].upper()
        team_id = by_code.get(code or "")
        if team_id and team_id not in team_ids:
            team_ids.append(team_id)
    return MappedIdentity(permissions=perms, team_ids=team_ids)

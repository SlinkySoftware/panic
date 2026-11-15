"""Security Zone & IP CIDR Resolution Engine (SPEC §4.4)."""

from __future__ import annotations

import ipaddress

from pydantic import BaseModel, Field

from panic_common.models import CatalogItem, SecurityZone


class ZoneMatchCandidate(BaseModel):
    zone_id: str
    zone_name: str
    matched_cidr: str
    prefix_len: int
    priority: int


class ZoneResolutionResult(BaseModel):
    client_ip: str
    valid_ip: bool = True
    winning_zone: SecurityZone | None = None
    matched_cidr: str | None = None
    candidates: list[ZoneMatchCandidate] = Field(default_factory=list)


class ReachabilityResult(BaseModel):
    reachable: bool
    zone_allowed: bool
    reason: str = "Reachable"
    badge_label: str = ""


def validate_cidr_list(cidrs: list[str]) -> list[str]:
    """Validate and canonicalize a list of IPv4/IPv6 CIDRs, raising ValueError on invalid input."""
    normalized: list[str] = []
    for raw in cidrs:
        cleaned = raw.strip()
        if not cleaned:
            continue
        net = ipaddress.ip_network(cleaned, strict=False)
        normalized.append(str(net))
    return normalized


def resolve_ip_zone(
    ip_str: str,
    zones: list[SecurityZone],
) -> ZoneResolutionResult:
    """Resolve a connecting client / jump-host IP against defined Security Zone CIDRs.

    Longest matching prefix wins. Ties: the zone with the smallest total address space (same IP version),
    then the highest Zone ``priority``, then the zone name.
    """
    cleaned_ip = ip_str.strip()
    try:
        addr = ipaddress.ip_address(cleaned_ip)
    except ValueError:
        return ZoneResolutionResult(client_ip=cleaned_ip, valid_ip=False)

    candidates: list[ZoneMatchCandidate] = []
    zone_by_id: dict[str, SecurityZone] = {z.id: z for z in zones}

    for zone in zones:
        for cidr in zone.cidrs:
            try:
                net = ipaddress.ip_network(cidr.strip(), strict=False)
            except ValueError:
                continue
            if addr.version == net.version and addr in net:
                candidates.append(
                    ZoneMatchCandidate(
                        zone_id=zone.id,
                        zone_name=zone.name,
                        matched_cidr=str(net),
                        prefix_len=net.prefixlen,
                        priority=zone.priority,
                    )
                )

    # Most specific first: longest matching prefix; on a tie, the zone covering the fewest addresses
    # overall (a zone that is just this /22 beats one spanning several networks); then higher priority;
    # then name, so the result never depends on input order.
    def zone_size(zone_id: str) -> int:
        total = 0
        for cidr in zone_by_id[zone_id].cidrs:
            try:
                net = ipaddress.ip_network(cidr.strip(), strict=False)
            except ValueError:
                continue
            if net.version == addr.version:
                total += net.num_addresses
        return total

    candidates.sort(key=lambda c: (-c.prefix_len, zone_size(c.zone_id), -c.priority, c.zone_name))

    winning_zone: SecurityZone | None = None
    matched_cidr: str | None = None
    if candidates:
        top = candidates[0]
        winning_zone = zone_by_id.get(top.zone_id)
        matched_cidr = top.matched_cidr

    return ZoneResolutionResult(
        client_ip=str(addr),
        valid_ip=True,
        winning_zone=winning_zone,
        matched_cidr=matched_cidr,
        candidates=candidates,
    )


def check_item_reachability(
    item: CatalogItem,
    active_zone: SecurityZone | None,
) -> ReachabilityResult:
    """Check whether ``item`` is allowed from ``active_zone`` (empty ``zone_ids`` means All Zones)."""
    zone_name = active_zone.name if active_zone else "Unclassified Zone"
    zone_id = active_zone.id if active_zone else None

    if item.zone_ids and (zone_id is None or zone_id not in item.zone_ids):
        return ReachabilityResult(
            reachable=False,
            zone_allowed=False,
            reason=f"Restricted to selected Zones (unavailable from {zone_name})",
            badge_label=f"Unavailable from {zone_name}",
        )

    return ReachabilityResult(
        reachable=True,
        zone_allowed=True,
        reason="Reachable from current Zone",
        badge_label="Reachable",
    )

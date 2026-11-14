"""Translate a pure :class:`panic_common.visibility.VisibilitySpec` into a Mongo filter (DATA_MODEL.md §5).

This is the one place that must stay in lock-step with ``panic_common.rbac.is_visible_in_scope``:
``Application/Server/tests/store/test_filters_visibility_parity.py`` checks the two against ~2,000
generated documents.
"""

from __future__ import annotations

from typing import Any

from panic_common.visibility import VisibilitySpec


def visibility_or(spec: VisibilitySpec) -> list[dict[str, Any]]:
    """The three scope branches of the visibility ``$or`` (DATA_MODEL.md §5), without orphan handling."""
    team_branch: dict[str, Any] = {"scope": "TEAM"}
    if not spec.all_teams:
        team_branch["team_ids"] = {"$in": list(spec.team_ids)}
    return [
        {"scope": "GLOBAL"},
        team_branch,
        {"scope": "PERSONAL", "owner_usernames": spec.username},
    ]


def visibility_filter(spec: VisibilitySpec) -> dict[str, Any]:
    """The full Mongo filter for a scoped collection (catalog_items, endpoint_lists, dashboards).

    Normal users: visible scope/team/owner branch AND not orphaned. Global Admins
    (``spec.all_teams``) additionally see every orphaned document (read-only, enforced
    elsewhere) via a second top-level ``$or`` branch.
    """
    base_or = {"$or": visibility_or(spec)}
    not_orphaned = {"orphaned": {"$ne": True}}
    if spec.all_teams:
        return {"$or": [{"$and": [base_or, not_orphaned]}, {"orphaned": True}]}
    return {"$and": [base_or, not_orphaned]}

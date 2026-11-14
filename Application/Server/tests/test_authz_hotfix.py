"""Regression tests for ADR-0001 findings F1-F3 (authorization gaps in the Stage 1-4 API)."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from panic_server.state import STORE


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    STORE.reset()


def _as(user_id: str) -> Client:
    client = Client()
    resp = client.post(
        "/api/v1/simulator", data=json.dumps({"active_user_id": user_id}), content_type="application/json"
    )
    assert resp.status_code == 200
    return client


def _post_rbac(client: Client, payload: dict[str, object]) -> int:
    resp = client.post("/api/v1/rbac", data=json.dumps(payload), content_type="application/json")
    return resp.status_code


def test_f1_non_admin_cannot_change_rbac() -> None:
    client = _as("usr-standard")
    assert (
        _post_rbac(client, {"action": "update_user", "user_id": "usr-standard", "permissions": ["GLOBAL_ADMIN"]}) == 403
    )
    assert _post_rbac(client, {"action": "create_user", "username": "intruder", "permissions": ["GLOBAL_ADMIN"]}) == 403
    user = next(u for u in STORE.users if u.id == "usr-standard")
    assert [p.value for p in user.permissions] == []
    assert not any(u.username == "intruder" for u in STORE.users)


def test_f1_admin_can_still_change_rbac() -> None:
    client = _as("usr-admin")
    assert (
        _post_rbac(client, {"action": "update_user", "user_id": "usr-standard", "permissions": ["CAN_ADD_TEAM"]}) == 200
    )


def test_f2_audit_log_is_admin_only() -> None:
    STORE.record_audit(action="catalog.create", target_type="catalog_item", target_id="cat-x", summary="secret")
    client = _as("usr-standard")
    assert client.get("/api/v1/audit").status_code == 403
    assert client.get("/api/v1/state").json()["audit_logs"] == []

    admin = _as("usr-admin")
    assert admin.get("/api/v1/audit").status_code == 200
    assert admin.get("/api/v1/state").json()["audit_logs"]


def test_f3_rdp_download_requires_visibility() -> None:
    # sam.reeves is only in team-secops; cat-team-rdp-compute is a team-compute item.
    client = _as("usr-team-lead")
    assert client.get("/api/v1/launch/rdp/cat-team-rdp-compute.rdp").status_code == 404

    admin = _as("usr-admin")
    assert admin.get("/api/v1/launch/rdp/cat-team-rdp-compute.rdp").status_code == 200

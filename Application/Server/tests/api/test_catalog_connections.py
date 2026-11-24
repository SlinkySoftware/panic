"""Multi-protocol catalog items over the API: one host, several ``connections`` (URL/SSH/RDP/LOCAL_APP)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from django.conf import settings as django_settings
from django.test import Client

from panic_server.context import SESSION_USER_KEY
from panic_server.store.repos import catalog as catalog_repo
from panic_server.store.repos import users as users_repo
from panic_server.store.repos import zones as zones_repo

pytestmark = [pytest.mark.mongo]


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _client_as(user_id: str) -> Client:
    client = Client()
    session = client.session
    session[SESSION_USER_KEY] = user_id
    session.save()
    client.cookies[django_settings.SESSION_COOKIE_NAME] = session.session_key
    return client


def _post(client: Client, path: str, body: dict[str, Any]) -> Any:
    return client.post(path, data=json.dumps(body), content_type="application/json")


@pytest.fixture(autouse=True)
def _default_zone(mongo_db: Any) -> None:
    zones_repo.ensure_default_zone(mongo_db)


@pytest.fixture
def client(mongo_db: Any) -> Client:
    username = _unique("conn-user")
    user = users_repo.create_user(mongo_db, username=username, display_name="Conn", default_remote_user=username)
    return _client_as(user.id)


def _create(client: Client, host: str, connections: list[dict[str, Any]], **extra: Any) -> Any:
    body = {"title": host, "host": host, "connections": connections, "scope": "PERSONAL", **extra}
    return _post(client, "/api/v1/catalog", body)


def test_create_ssh_and_url_item_orders_connections_and_launches_both(client: Client) -> None:
    host = f"{_unique('fw')}.example.net"
    resp = _create(client, host, [{"protocol": "URL", "path_or_args": "/ui"}, {"protocol": "SSH", "port": 2222}])
    assert resp.status_code == 201, resp.content
    item = resp.json()
    assert [c["protocol"] for c in item["connections"]] == ["SSH", "URL"]  # SSH is the primary
    assert item["normalized_keys"] == [f"ssh://{host}:2222", f"url://{host}:443/ui"]

    rows = client.get("/api/v1/catalog", {"group": "personal", "q": host.split(".")[0]}).json()["results"]
    view = next(r for r in rows if r["id"] == item["id"])
    assert view["protocol"] == "SSH"
    assert view["protocols"] == ["SSH", "URL"]
    assert view["target"] == f"{host}:2222"
    assert view["launch"]["kind"] == "COPY"
    assert "protocol" not in view["launch"]  # the primary's protocol/target are the view's own
    assert len(view["alt_launches"]) == 1
    alt = view["alt_launches"][0]
    assert alt["protocol"] == "URL"
    assert alt["kind"] == "OPEN"
    assert alt["url"] == f"https://{host}/ui"


def test_ssh_with_rdp_is_rejected(client: Client) -> None:
    resp = _create(client, f"{_unique('win')}.example.net", [{"protocol": "SSH"}, {"protocol": "RDP"}])
    assert resp.status_code == 400
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "connections" in body["fields"]


@pytest.mark.parametrize(
    "connections",
    [[], [{"protocol": "WEB"}], [{"protocol": "URL"}, {"protocol": "URL"}]],
    ids=["none", "unknown-protocol", "repeated"],
)
def test_invalid_connections_are_rejected(client: Client, connections: list[dict[str, Any]]) -> None:
    resp = _create(client, f"{_unique('bad')}.example.net", connections)
    assert resp.status_code == 400
    assert "connections" in resp.json()["fields"]


def test_duplicate_detected_when_any_connection_key_overlaps(client: Client) -> None:
    host = f"{_unique('dup')}.example.net"
    first = _create(client, host, [{"protocol": "SSH"}])
    assert first.status_code == 201, first.content

    # Same host, but only a URL connection: no key in common with the SSH-only item, so no clash.
    assert _create(client, host, [{"protocol": "URL"}]).status_code == 201

    # Shares the SSH key with the first item, alongside a new LOCAL_APP connection: duplicate.
    clash = _create(client, host, [{"protocol": "LOCAL_APP", "path_or_args": "putty"}, {"protocol": "SSH"}])
    assert clash.status_code == 409
    assert clash.json()["error_code"] == "DUPLICATE_CATALOG_ITEM"
    assert clash.json()["existing_item"]["id"] == first.json()["id"]

    preview = _post(
        client, "/api/v1/catalog/preview", {"host": host, "connections": [{"protocol": "SSH"}], "scope": "PERSONAL"}
    ).json()
    assert preview["normalized_keys"] == [f"ssh://{host}:22"]
    assert preview["duplicate"]["id"] == first.json()["id"]

    # Excluding the item itself (an edit preview) reports no duplicate.
    preview_self = _post(
        client,
        "/api/v1/catalog/preview",
        {"host": host, "connections": [{"protocol": "SSH"}], "scope": "PERSONAL", "item_id": first.json()["id"]},
    ).json()
    assert preview_self["duplicate"] is None


def test_protocol_filter_matches_non_primary_connection(client: Client) -> None:
    tag = _unique("filt")
    host = f"{tag}.example.net"
    multi = _create(client, host, [{"protocol": "SSH"}, {"protocol": "URL"}], tags=[tag]).json()
    ssh_only = _create(client, f"{tag}-ssh.example.net", [{"protocol": "SSH"}], tags=[tag]).json()

    def ids(protocol: str) -> set[str]:
        resp = client.get("/api/v1/catalog", {"group": "personal", "q": tag, "protocol": protocol})
        return {r["id"] for r in resp.json()["results"]}

    assert ids("URL") == {multi["id"]}
    assert ids("SSH") == {multi["id"], ssh_only["id"]}


def test_patch_connections_renormalizes_and_ignores_unknown_fields(client: Client, mongo_db: Any) -> None:
    host = f"{_unique('patch')}.example.net"
    item = _create(client, host, [{"protocol": "SSH"}]).json()
    resp = client.patch(
        f"/api/v1/catalog/{item['id']}",
        data=json.dumps({"connections": [{"protocol": "RDP", "port": 3390}], "normalized_keys": ["forged"]}),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    stored = catalog_repo.get_catalog_item(mongo_db, item["id"])
    assert [c.protocol for c in stored.connections] == ["RDP"]
    assert stored.normalized_keys == [f"rdp://{host}:3390"]

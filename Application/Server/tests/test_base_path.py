"""URL prefix (``PANIC_BASE_PATH``): normalisation, the WSGI mount, and prefix-aware request handling."""

from __future__ import annotations

import io
from collections.abc import Iterable
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.handlers.wsgi import WSGIHandler
from django.test import Client, override_settings
from pymongo.database import Database

from panic_server.paths import app_path, mount, normalise_base_path
from panic_server.store.repos import zones as zones_repo


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), ("", ""), ("/", ""), ("panic", "/panic"), ("/panic/", "/panic"), ("//ops//panic/", "/ops/panic")],
)
def test_normalise_base_path(value: str | None, expected: str) -> None:
    assert normalise_base_path(value) == expected


@pytest.mark.parametrize("value", ["/pa nic", "/panic.v2", "/../panic", "/pan$ic", "/~panic", "/panic?x"])
def test_normalise_base_path_rejects_unsafe_segments(value: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="PANIC_BASE_PATH"):
        normalise_base_path(value)


def test_app_path() -> None:
    with override_settings(PANIC_BASE_PATH=""):
        assert app_path("/login") == "/login"
    with override_settings(PANIC_BASE_PATH="/panic"):
        assert app_path("/login") == "/panic/login"
        assert app_path("api/v1/export") == "/panic/api/v1/export"


def _seen(base: str, path: str) -> tuple[str, str]:
    environ: dict[str, Any] = {"SCRIPT_NAME": "", "PATH_INFO": path}

    def app(env: dict[str, Any], start_response: Any) -> Iterable[bytes]:
        return [f"{env['SCRIPT_NAME']}|{env['PATH_INFO']}".encode()]

    body = b"".join(mount(app, base)(environ, lambda *a: None)).decode()
    script, _, info = body.partition("|")
    return script, info


@pytest.mark.parametrize(
    ("path", "script", "info"),
    [
        ("/panic/api/v1/health", "/panic", "/api/v1/health"),
        ("/panic", "/panic", "/"),
        ("/panic/", "/panic", "/"),
        ("/api/v1/health", "", "/api/v1/health"),  # health check and /metrics on the server port
        ("/panicky/x", "", "/panicky/x"),  # only a whole segment matches
    ],
)
def test_mount_moves_the_prefix_into_script_name(path: str, script: str, info: str) -> None:
    assert _seen("/panic", path) == (script, info)


def test_mount_without_prefix_is_the_app_itself() -> None:
    app = WSGIHandler()
    assert mount(app, "") is app


@pytest.mark.mongo
def test_prefixed_request_through_the_mount(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)
    app = mount(WSGIHandler(), "/panic")

    def get(path: str) -> str:
        status: list[str] = []
        environ = {
            "REQUEST_METHOD": "GET",
            "SCRIPT_NAME": "",
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "SERVER_NAME": "testserver",
            "SERVER_PORT": "80",
            "HTTP_HOST": "testserver",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(),
            "wsgi.errors": io.StringIO(),
        }
        b"".join(app(environ, lambda s, h, *a: status.append(s)))
        return status[0]

    assert get("/panic/api/v1/health").startswith("200")
    assert get("/api/v1/health").startswith("200")
    assert get("/panic/api/v1/ui/bootstrap").startswith("401")


@pytest.mark.mongo
def test_anonymous_page_request_redirects_to_the_prefixed_login(mongo_db: Database) -> None:
    zones_repo.ensure_default_zone(mongo_db)
    with override_settings(PANIC_BASE_PATH="/panic"):
        resp = Client().get("/somewhere", {"a": "1"}, SCRIPT_NAME="/panic")
    assert resp.status_code == 302
    assert resp["Location"] == "/panic/login?next=/somewhere%3Fa%3D1"

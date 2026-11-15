"""Documentation guard: every ``PANIC_*`` setting must be documented in CONFIGURATION.md.

The Stage 1-5 STORE-backed end-to-end workflows this file used to cover (session auth + CSRF +
relational persistence + trusted-proxy zone resolution + RBAC + launchers, T-S4-02) were deleted
in T-S6-04 along with ``STORE``/``state.py``/the whole server-rendered UI; their replacements
live in ``tests/test_auth.py`` and ``tests/test_proxy_middleware.py``. This one check is pure
filesystem/regex logic independent of ``STORE``, so it survives, updated for the settings T-S6-04
removed/added.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


_READ = re.compile(r'(?:env_\w+|environ\.get|getenv)\(\s*"(PANIC_[A-Z0-9_]+)"|\$\{(PANIC_[A-Z0-9_]+)')
REMOVED = {
    "PANIC_DB_ENGINE",
    "PANIC_DB_HOST",
    "PANIC_DB_PORT",
    "PANIC_DB_NAME",
    "PANIC_DB_USER",
    "PANIC_DB_PASSWORD",
    "PANIC_DB_CONN_MAX_AGE",
    "PANIC_SQLITE_PATH",
    "PANIC_STATIC_ROOT",
    "PANIC_AUTO_SEED",
    "PANIC_AUTH_MODE",
    "PANIC_OIDC_GROUPS_CLAIM",
    "PANIC_LDAP_GROUP_BASE_DN",
    "PANIC_LDAP_GROUP_FILTER",
    "PANIC_RBAC_ADMIN_GROUPS",
    "PANIC_RBAC_GLOBAL_CONTRIB_GROUPS",
    "PANIC_RBAC_TEAM_CONTRIB_GROUPS",
    "PANIC_RBAC_TEAM_GROUP_MAP",
    "PANIC_RBAC_TEAM_GROUP_PREFIX",
    "PANIC_CACHE_URL",
}


def _read_settings() -> set[str]:
    """Every PANIC_* variable read by the server code, both images and the compose files."""
    sources = [
        *(ROOT / "Application/Server/panic_server").rglob("*.py"),
        *(ROOT / "Build/Containers").rglob("*.sh"),
        *(ROOT / "Build/Containers").rglob("*.envsh"),
        *(ROOT / "Build/Containers").rglob("*.py"),
        *(ROOT / "Build/Containers").glob("compose*.yaml"),
    ]
    names: set[str] = set()
    for path in sources:
        for a, b in _READ.findall(path.read_text()):
            names.add(a or b)
    return names


def test_configuration_doc_covers_every_setting() -> None:
    names = _read_settings()
    assert {"PANIC_MONGO_URI", "PANIC_SERVER_URL", "PANIC_GUNICORN_THREADS"} <= names  # the scan works
    doc = (ROOT / "Documents/Operations/CONFIGURATION.md").read_text()
    missing = sorted(n for n in names if f"`{n}`" not in doc)
    assert not missing, f"undocumented settings: {missing}"
    deploy = (ROOT / "Documents/Operations/DEPLOYMENT.md").read_text()
    assert "CONFIGURATION.md" in deploy and "panic_export" in deploy


def test_removed_settings_are_listed_and_no_longer_read() -> None:
    doc = (ROOT / "Documents/Operations/CONFIGURATION.md").read_text()
    removed_section = doc.split("## Removed in Stage 6", 1)[1].split("\n## ", 1)[0]
    assert all(f"`{n}`" in removed_section for n in REMOVED)
    assert not (REMOVED & _read_settings())

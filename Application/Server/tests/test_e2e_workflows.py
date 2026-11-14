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


def test_configuration_doc_covers_every_setting() -> None:
    settings_src = (ROOT / "Application/Server/panic_server/settings.py").read_text()
    entry_src = (ROOT / "Build/Containers/server/entrypoint.sh").read_text()
    names = set(re.findall(r'env_\w+\("(PANIC_[A-Z0-9_]+)"', settings_src))
    names |= set(re.findall(r"\$\{(PANIC_[A-Z0-9_]+)", entry_src))
    doc = (ROOT / "Documents/Operations/CONFIGURATION.md").read_text()
    missing = sorted(n for n in names if f"`{n}`" not in doc)
    assert not missing, f"undocumented settings: {missing}"
    deploy = (ROOT / "Documents/Operations/DEPLOYMENT.md").read_text()
    assert "CONFIGURATION.md" in deploy and "panic_export" in deploy

"""T-S6-12: the nginx template proxies exactly the allow-list (AR-6.4) and never /metrics."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "gen_nginx_conf.py"
_spec = importlib.util.spec_from_file_location("gen_nginx_conf", _SCRIPT)
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _conf() -> tuple[str, list[str], list[str]]:
    prefixes, exact = gen.load_paths(gen.DEFAULT_PATHS)
    return gen.render(prefixes, exact), prefixes, exact


def test_every_allow_listed_path_is_proxied_and_nothing_else() -> None:
    conf, prefixes, exact = _conf()
    proxied = re.findall(r"location (\^~|=) (\S+) \{\n\s+proxy_pass", conf)
    assert sorted(p for kind, p in proxied if kind == "^~") == sorted(prefixes)
    assert sorted(p for kind, p in proxied if kind == "=") == sorted(exact)
    assert conf.count("proxy_pass") == len(prefixes) + len(exact)


def test_metrics_is_blocked_and_unlisted_api_paths_404() -> None:
    conf, _, _ = _conf()
    assert "location = /metrics { return 404; }" in conf
    assert "location ^~ /api/ { return 404; }" in conf
    assert not re.search(r"location[^{]*/metrics[^{]*\{\s*proxy_pass", conf)


def test_only_panic_server_url_is_an_envsubst_variable() -> None:
    conf, _, _ = _conf()
    assert set(re.findall(r"\$\{(\w+)\}", conf)) == {"PANIC_SERVER_URL"}
    assert "X-Forwarded-For $proxy_add_x_forwarded_for" in conf


def test_rejects_metrics_and_unsafe_paths(tmp_path: Path) -> None:
    for bad in ({"prefixes": [], "exact": ["/metrics"]}, {"prefixes": ["/api/v1/x"], "exact": []},
                {"prefixes": [], "exact": ["/api/v1/x;evil"]}):
        p = tmp_path / "paths.json"
        p.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            gen.load_paths(p)


def test_committed_allow_list_is_what_the_dev_proxy_reads() -> None:
    data = json.loads(gen.DEFAULT_PATHS.read_text())
    assert "/metrics" not in data["exact"] and all("/metrics" not in p for p in data["prefixes"])

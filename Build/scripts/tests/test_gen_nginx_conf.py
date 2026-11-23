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
    proxied = re.findall(r"location (\^~|=) \$\{PANIC_BASE_PATH\}(\S+) \{\n\s+proxy_pass", conf)
    assert sorted(p for kind, p in proxied if kind == "^~") == sorted(prefixes)
    assert sorted(p for kind, p in proxied if kind == "=") == sorted(exact)
    assert conf.count("proxy_pass") == len(prefixes) + len(exact)


def test_metrics_is_blocked_and_unlisted_api_paths_404() -> None:
    conf, _, _ = _conf()
    assert "location = ${PANIC_BASE_PATH}/metrics { return 404; }" in conf
    assert "location ^~ ${PANIC_BASE_PATH}/api/ { return 404; }" in conf
    assert not re.search(r"location[^{]*/metrics[^{]*\{\s*proxy_pass", conf)


def test_only_the_server_url_and_base_path_are_envsubst_variables() -> None:
    conf, _, _ = _conf()
    assert set(re.findall(r"\$\{(\w+)\}", conf)) == {"PANIC_SERVER_URL", "PANIC_BASE_PATH"}
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


def test_every_location_but_healthz_is_under_the_base_path() -> None:
    conf, _, _ = _conf()
    plain = re.findall(r"location (?:\^~|=) (/\S*) \{", conf)
    assert plain == ["/healthz"]
    assert "rewrite ^${PANIC_BASE_PATH}(/.*)$ $1 break;" in conf
    assert conf.count("""sub_filter '<base href="/">' '<base href="${PANIC_BASE_PATH}/">';""") == 2
    assert "location ~ ^${PANIC_BASE_PATH}$ { return 301 ${PANIC_BASE_PATH}/; }" in conf

"""Search key tokeniser for catalog items, lists, dashboards and users (DATA_MODEL §4.10)."""

from __future__ import annotations

import re
from collections.abc import Iterable

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(value: str) -> list[str]:
    lowered = value.strip().lower()
    if not lowered:
        return []
    return [tok for tok in _TOKEN_SPLIT_RE.split(lowered) if tok]


def search_keys(
    title: str = "",
    host: str = "",
    site: str = "",
    tags: Iterable[str] = (),
    *extra: str,
) -> list[str]:
    """Tokenise ``title``/``host``/``site``/``tags``/``extra`` into lower-cased, anchored-prefix keys.

    ``host`` is also kept whole (lower-cased) alongside its split tokens, so that
    ``{search_keys: {$regex: "^tok"}}`` can match on the full hostname too.
    """
    tokens: set[str] = set()
    for value in (title, host, site, *extra):
        tokens.update(_tokenize(value))
    for tag in tags:
        tokens.update(_tokenize(tag))
    cleaned_host = host.strip().lower()
    if cleaned_host:
        tokens.add(cleaned_host)
    return sorted(tokens)

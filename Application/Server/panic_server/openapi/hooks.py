"""drf-spectacular schema-generation hooks for the PANIC API.

Just one so far: describing :class:`panic_server.api.authentication.RequestContextAuthentication`
(session-cookie based, no bearer token) as an OpenAPI security scheme, so ``manage.py spectacular
--fail-on-warn`` does not warn about an unrecognised authenticator on every authenticated/admin
view. Imported for its side effect (extension registration) by ``panic_server.api.urls``, which
every management command that walks the URLconf (including ``spectacular``) always loads.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class PanicSessionAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    # drf-spectacular's ``OpenApiGeneratorExtension.__init_subclass__`` (registry bookkeeping)
    # is itself untyped; subclassing it always trips mypy's untyped-call check regardless of
    # this project's own strictness settings.
    target_class = "panic_server.api.authentication.RequestContextAuthentication"
    name = "panicSessionAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "panic_sessionid",
            "description": (
                "Session cookie (API.md §1). Unsafe methods also require X-CSRFToken "
                "matching the panic_csrftoken cookie."
            ),
        }


__all__ = ["PanicSessionAuthenticationScheme"]

"""LDAP / LDAPS bind authentication and group lookup adapter.

Flow: (optional) service-account bind -> search the user's DN -> bind as the user with the supplied
password -> search group memberships. All filter values are escaped (RFC 4515).
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from ldap3 import NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars


class LdapError(Exception):
    """Directory unreachable or misconfigured (distinct from bad credentials)."""


@dataclass(frozen=True)
class LdapIdentity:
    username: str
    display_name: str
    groups: list[str]


def _server() -> Server:
    tls = None
    uri = settings.PANIC_LDAP_URI
    if uri.lower().startswith("ldaps://") or settings.PANIC_LDAP_START_TLS:
        tls = Tls(
            validate=ssl.CERT_REQUIRED,
            ca_certs_file=settings.PANIC_LDAP_CA_CERT_FILE or None,
        )
    return Server(uri, get_info=NONE, tls=tls, connect_timeout=settings.PANIC_LDAP_TIMEOUT_S)


def _connection(server: Server, user: str | None, password: str | None) -> Connection:
    conn = Connection(
        server,
        user=user,
        password=password,
        auto_bind=False,
        receive_timeout=settings.PANIC_LDAP_TIMEOUT_S,
        raise_exceptions=False,
    )
    conn.open()
    if settings.PANIC_LDAP_START_TLS and not settings.PANIC_LDAP_URI.lower().startswith("ldaps://"):
        conn.start_tls()
    return conn


def _first(entry_attrs: dict[str, Any], attr: str) -> str:
    value = entry_attrs.get(attr)
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def authenticate(username: str, password: str) -> LdapIdentity | None:
    """Return the directory identity on a successful user bind, ``None`` on bad credentials."""
    if not settings.PANIC_LDAP_ENABLED or not username or not password:
        return None
    try:
        server = _server()
        svc = _connection(server, settings.PANIC_LDAP_BIND_DN or None, settings.PANIC_LDAP_BIND_PASSWORD or None)
        if not svc.bind():
            raise LdapError("service bind failed")
        user_filter = settings.PANIC_LDAP_USER_FILTER.format(username=escape_filter_chars(username))
        svc.search(
            settings.PANIC_LDAP_USER_BASE_DN,
            user_filter,
            SUBTREE,
            attributes=[settings.PANIC_LDAP_USERNAME_ATTR, settings.PANIC_LDAP_DISPLAY_NAME_ATTR],
            size_limit=2,
        )
        # Only real entries count: Active Directory searched from the domain root also returns
        # referrals (searchResRef) to its other partitions, which are not matches.
        entries = [r for r in svc.response or [] if r.get("type") == "searchResEntry"]
        if len(entries) != 1:
            svc.unbind()
            return None
        entry = entries[0]
        user_dn = str(entry["dn"])
        attrs = dict(entry.get("attributes") or {})

        user_conn = _connection(server, user_dn, password)
        ok = user_conn.bind()
        user_conn.unbind()
        if not ok:
            svc.unbind()
            return None

        # No group search -- external identity is for authentication only (ADR-0001
        # decision 11), so PANIC does not read or map directory groups at all.
        groups: list[str] = []
        svc.unbind()
    except LDAPException as e:
        raise LdapError(f"{type(e).__name__}: {e}") from e
    resolved_username = _first(attrs, settings.PANIC_LDAP_USERNAME_ATTR) or username
    return LdapIdentity(
        username=resolved_username,
        display_name=_first(attrs, settings.PANIC_LDAP_DISPLAY_NAME_ATTR) or resolved_username,
        groups=groups,
    )

"""PANIC Server settings. Every setting comes from the environment (AR-3.1); see ``.env.example``."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured

from panic_server import __version__
from panic_server.conf import env_bool, env_int, env_list, env_str
from panic_server.logging import logging_config

PANIC_ENV = env_str("PANIC_ENV", "dev")
if PANIC_ENV not in {"dev", "test", "prod"}:
    raise ImproperlyConfigured("PANIC_ENV must be one of dev|test|prod")
IS_PROD = PANIC_ENV == "prod"

_PLACEHOLDER_SECRET = "change-me-to-a-long-random-string"  # noqa: S105
SECRET_KEY = env_str("PANIC_DJANGO_SECRET_KEY", "dev-insecure-" + "0" * 40)
if IS_PROD and (SECRET_KEY == _PLACEHOLDER_SECRET or SECRET_KEY.startswith("dev-insecure-") or len(SECRET_KEY) < 32):
    raise ImproperlyConfigured("PANIC_DJANGO_SECRET_KEY must be set to a long random value in prod")

DEBUG = env_bool("PANIC_DEBUG", not IS_PROD)
ALLOWED_HOSTS = env_list("PANIC_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver,*")
CSRF_TRUSTED_ORIGINS = env_list("PANIC_CSRF_TRUSTED_ORIGINS")

PANIC_INSTANCE_NAME = env_str("PANIC_INSTANCE_NAME", "PANIC")

# ---------------------------------------------------------------- Reverse proxy / Security Zones (AR-5)
PANIC_TRUST_PROXY_HEADERS = env_bool("PANIC_TRUST_PROXY_HEADERS", True)
_PANIC_PROXY_IP_HEADER_CHOICES = {"X-Forwarded-For", "Forwarded"}
PANIC_PROXY_IP_HEADER = env_str("PANIC_PROXY_IP_HEADER", "X-Forwarded-For")
if PANIC_PROXY_IP_HEADER not in _PANIC_PROXY_IP_HEADER_CHOICES:
    # T-S6-04 removes the "X-Real-IP" option (AR-5.1: panic-web never sets it; the design has no
    # use for it, dev or prod) -- only the two hop-chain-aware forms below remain valid.
    raise ImproperlyConfigured("PANIC_PROXY_IP_HEADER must be X-Forwarded-For or Forwarded")
PANIC_TRUSTED_PROXY_CIDRS = env_list("PANIC_TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
PANIC_UNTRUSTED_PEER_POLICY = env_str("PANIC_UNTRUSTED_PEER_POLICY", "default")
if PANIC_UNTRUSTED_PEER_POLICY not in {"default", "reject"}:
    raise ImproperlyConfigured("PANIC_UNTRUSTED_PEER_POLICY must be default|reject")
PANIC_XFF_MAX_HOPS = env_int("PANIC_XFF_MAX_HOPS", 16)
PANIC_XFF_MAX_BYTES = env_int("PANIC_XFF_MAX_BYTES", 4096)


# ---------------------------------------------------------------- Authentication (Stage 3, hardened T-S6-04)
# There is no simulator left (ADR-0001 decision 6): identity always comes from a real sign-in
# (local bootstrap admin, OIDC, LDAP) and the session engine below.
PANIC_AUTH_LOCAL_ENABLED = env_bool("PANIC_AUTH_LOCAL_ENABLED", True)
PANIC_BOOTSTRAP_ADMIN_USER = env_str("PANIC_BOOTSTRAP_ADMIN_USER", "")
PANIC_BOOTSTRAP_ADMIN_PASSWORD = env_str("PANIC_BOOTSTRAP_ADMIN_PASSWORD", "")

PANIC_OIDC_ENABLED = env_bool("PANIC_OIDC_ENABLED", False)
PANIC_OIDC_PROVIDER_NAME = env_str("PANIC_OIDC_PROVIDER_NAME", "Single Sign-On")
PANIC_OIDC_ISSUER = env_str("PANIC_OIDC_ISSUER", "")
PANIC_OIDC_CLIENT_ID = env_str("PANIC_OIDC_CLIENT_ID", "")
PANIC_OIDC_CLIENT_SECRET = env_str("PANIC_OIDC_CLIENT_SECRET", "")
PANIC_OIDC_AUTHORIZE_URL = env_str("PANIC_OIDC_AUTHORIZE_URL", "")
PANIC_OIDC_TOKEN_URL = env_str("PANIC_OIDC_TOKEN_URL", "")
PANIC_OIDC_USERINFO_URL = env_str("PANIC_OIDC_USERINFO_URL", "")
PANIC_OIDC_REDIRECT_URI = env_str("PANIC_OIDC_REDIRECT_URI", "")
PANIC_OIDC_SCOPES = env_str("PANIC_OIDC_SCOPES", "openid profile email groups")
PANIC_OIDC_USERNAME_CLAIM = env_str("PANIC_OIDC_USERNAME_CLAIM", "preferred_username")
PANIC_OIDC_DISPLAY_NAME_CLAIM = env_str("PANIC_OIDC_DISPLAY_NAME_CLAIM", "name")
PANIC_OIDC_TIMEOUT_S = env_int("PANIC_OIDC_TIMEOUT_S", 5)

PANIC_LDAP_ENABLED = env_bool("PANIC_LDAP_ENABLED", False)
PANIC_LDAP_URI = env_str("PANIC_LDAP_URI", "")
PANIC_LDAP_START_TLS = env_bool("PANIC_LDAP_START_TLS", False)
PANIC_LDAP_CA_CERT_FILE = env_str("PANIC_LDAP_CA_CERT_FILE", "")
PANIC_LDAP_BIND_DN = env_str("PANIC_LDAP_BIND_DN", "")
PANIC_LDAP_BIND_PASSWORD = env_str("PANIC_LDAP_BIND_PASSWORD", "")
PANIC_LDAP_USER_BASE_DN = env_str("PANIC_LDAP_USER_BASE_DN", "")
PANIC_LDAP_USER_FILTER = env_str("PANIC_LDAP_USER_FILTER", "(uid={username})")
PANIC_LDAP_USERNAME_ATTR = env_str("PANIC_LDAP_USERNAME_ATTR", "uid")
PANIC_LDAP_DISPLAY_NAME_ATTR = env_str("PANIC_LDAP_DISPLAY_NAME_ATTR", "displayName")
PANIC_LDAP_TIMEOUT_S = env_int("PANIC_LDAP_TIMEOUT_S", 5)

# T-S6-04: external identity is authentication only. panic_common.claim_mapping, the OIDC groups
# claim setting, the LDAP group-search settings, and every PANIC_RBAC_* group-mapping setting are
# gone -- permissions and team membership only ever come from the users pages (ADR-0001 decision 11).

ROOT_URLCONF = "panic_server.urls"
WSGI_APPLICATION = "panic_server.wsgi.application"
APPEND_SLASH = False

INSTALLED_APPS = [
    "rest_framework",
    "drf_spectacular",
    "panic_server",
]

MIDDLEWARE = [
    "panic_server.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "panic_server.security.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    # Resolves request.context: real/effective identity, client IP and Security Zone (T-S6-04).
    "panic_server.middleware.RequestContextMiddleware",
    # Per-client-IP (and per-username, for /login) limits, backed by Mongo (T-S3-04, T-S6-04).
    "panic_server.security.RateLimitMiddleware",
    # Binds the authenticated session user to the request (Stage 3, T-S6-04).
    "panic_server.auth.middleware.PanicAuthMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# T-S6-04: Mongo-backed sessions (DATA_MODEL.md §4.11, AR-4.7) -- there is no relational DATABASES
# left, so the db-backed django.contrib.sessions.backends.db engine is not an option, and
# "django.contrib.sessions" need not be an installed app either (its app only supplies the
# django_session model/migration used by that db backend, and the clearsessions command -- a
# no-op here, since the sessions collection's TTL index on expire_at reclaims expired rows).
SESSION_ENGINE = "panic_server.store.sessions"
SESSION_COOKIE_NAME = "panic_sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("PANIC_SESSION_COOKIE_SECURE", IS_PROD)
SESSION_COOKIE_AGE = env_int("PANIC_SESSION_AGE_S", 8 * 3600)

LANGUAGE_CODE = "en-au"
TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = False
PANIC_TZ = env_str("PANIC_TZ", "UTC")

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = env_bool("PANIC_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = env_int("PANIC_HSTS_SECONDS", 0)
if env_bool("PANIC_SECURE_PROXY_SSL_HEADER", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------- CSRF, CSP, rate limiting (T-S3-04)
CSRF_COOKIE_NAME = "panic_csrftoken"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_FAILURE_VIEW = "panic_server.security.csrf_failure"
PANIC_CSP = env_str("PANIC_CSP", "")
PANIC_RATE_LIMIT_ENABLED = env_bool("PANIC_RATE_LIMIT_ENABLED", True)
PANIC_RATE_LIMIT_LOGIN = env_str("PANIC_RATE_LIMIT_LOGIN", "10/60")
PANIC_RATE_LIMIT_API = env_str("PANIC_RATE_LIMIT_API", "300/60")
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK: dict[str, Any] = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    # T-S6-06: bridges request.context (T-S6-04) into DRF's request.user; every view explicitly
    # declares one of panic_server.api.permissions' three tiers, and an undeclared view's default
    # (DenyAll) fails closed rather than silently falling through to public (AR-2.8).
    "DEFAULT_AUTHENTICATION_CLASSES": ["panic_server.api.authentication.RequestContextAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["panic_server.api.permissions.DenyAll"],
    "EXCEPTION_HANDLER": "panic_server.api.errors.exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# The committed contract Documents/Architecture/openapi/server.yaml is generated from these
# settings and the views (./panic contracts; CI fails when it is stale -- same pattern as
# reference-app). Nothing here may depend on the environment.
SPECTACULAR_SETTINGS: dict[str, Any] = {
    "TITLE": "PANIC Server API",
    "DESCRIPTION": (
        "All paths are under /api/v1 (AR-6.3). JSON only except the .rdp download "
        "(application/x-rdp). Times are RFC 3339 UTC.\n"
        "panic-web proxies only /api/v1/{ui,auth,me,dashboards,catalog,lists,sites,teams,zones,"
        "users,admin,launch/rdp}/*, /auth/oidc/*, /api/v1/health and /api/v1/version "
        "(Documents/Architecture/API.md §9); /metrics and /api/v1/schema are server-only.\n"
        "Generated by drf-spectacular (Documents/Architecture/openapi/server.yaml; regenerate "
        "with `./panic contracts`)."
    ),
    "VERSION": __version__,
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SCHEMA_PATH_PREFIX_TRIM": True,
    "SERVERS": [{"url": "/api/v1"}],
}

LOGGING = logging_config(
    env_str("PANIC_LOG_LEVEL", "INFO").upper(),
    env_str("PANIC_LOG_FORMAT", "json").lower(),
)

# ---------------------------------------------------------------- MongoDB (Stage 6, T-S6-02)
# panic_server.store is the only package that opens this (AR-4.1); see DATA_MODEL.md §2.
PANIC_MONGO_URI = env_str("PANIC_MONGO_URI", "")
PANIC_ZONE_CACHE_TTL_S = env_int("PANIC_ZONE_CACHE_TTL_S", 10)
PANIC_AUDIT_RETENTION_DAYS = env_int("PANIC_AUDIT_RETENTION_DAYS", 365)
# Test-only override so the test suite never touches a dev/prod database (see tests/conftest.py).
PANIC_TEST_MONGO_URI = env_str("PANIC_TEST_MONGO_URI", "")

# ---------------------------------------------------------------- UI read views (T-S6-06, DATA_MODEL.md §4.7)
#: Navigation menu cap (DATA_MODEL.md §4.7 "Navigation menu").
PANIC_NAV_MAX_DASHBOARDS = env_int("PANIC_NAV_MAX_DASHBOARDS", 100)
#: Per-LIST-widget item cap on a dashboard view (API.md §4.2); a list's own "Show all" page uses
#: the larger PANIC_LIST_MAX_ITEMS instead (T-S6-07's /api/v1/lists/{id}).
PANIC_LIST_WIDGET_MAX_ITEMS = env_int("PANIC_LIST_WIDGET_MAX_ITEMS", 200)

# ---------------------------------------------------------------- resources/mutations (T-S6-07)
#: Hard cap on an endpoint list's item_ids (DATA_MODEL.md §3); PUT/GET /api/v1/lists/{id} enforce this.
PANIC_LIST_MAX_ITEMS = env_int("PANIC_LIST_MAX_ITEMS", 500)

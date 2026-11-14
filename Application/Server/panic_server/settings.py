"""PANIC Server settings. Every setting comes from the environment (AR-3.1); see ``.env.example``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from panic_server.conf import env_bool, env_int, env_list, env_str
from panic_server.logging import logging_config

BASE_DIR = Path(__file__).resolve().parent

PANIC_ENV = env_str("PANIC_ENV", "dev")
if PANIC_ENV not in {"dev", "test", "prod"}:
    raise ImproperlyConfigured("PANIC_ENV must be one of dev|test|prod")
IS_PROD = PANIC_ENV == "prod"

_PLACEHOLDER_SECRET = "change-me-to-a-long-random-string"  # noqa: S105
SECRET_KEY = env_str("PANIC_DJANGO_SECRET_KEY", "dev-insecure-" + "0" * 40)
if IS_PROD and (
    SECRET_KEY == _PLACEHOLDER_SECRET or SECRET_KEY.startswith("dev-insecure-") or len(SECRET_KEY) < 32
):
    raise ImproperlyConfigured("PANIC_DJANGO_SECRET_KEY must be set to a long random value in prod")

DEBUG = env_bool("PANIC_DEBUG", not IS_PROD)
ALLOWED_HOSTS = env_list("PANIC_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver,*")
CSRF_TRUSTED_ORIGINS = env_list("PANIC_CSRF_TRUSTED_ORIGINS")

PANIC_INSTANCE_NAME = env_str("PANIC_INSTANCE_NAME", "PANIC")
PANIC_TRUST_PROXY_HEADERS = env_bool("PANIC_TRUST_PROXY_HEADERS", True)
PANIC_PROXY_IP_HEADER = env_str("PANIC_PROXY_IP_HEADER", "X-Forwarded-For")
PANIC_TRUSTED_PROXY_CIDRS = env_list("PANIC_TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
PANIC_ENTITLEMENT_CACHE_TTL_S = env_int("PANIC_ENTITLEMENT_CACHE_TTL_S", 30)
PANIC_ENTITLEMENT_TIMEOUT_S = env_int("PANIC_ENTITLEMENT_TIMEOUT_S", 3)

# ---------------------------------------------------------------- Authentication (Stage 3)
# simulator: dev/test RBAC simulator (no login). session: real login (local bootstrap admin, OIDC, LDAP).
PANIC_AUTH_MODE = env_str("PANIC_AUTH_MODE", "session" if IS_PROD else "simulator").lower()
if PANIC_AUTH_MODE not in {"simulator", "session"}:
    raise ImproperlyConfigured("PANIC_AUTH_MODE must be simulator|session")
if IS_PROD and PANIC_AUTH_MODE == "simulator":
    raise ImproperlyConfigured("PANIC_AUTH_MODE=simulator is not permitted when PANIC_ENV=prod")
PANIC_DEV_SIMULATOR_ENABLED = env_bool("PANIC_DEV_SIMULATOR_ENABLED", PANIC_AUTH_MODE == "simulator")
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
PANIC_OIDC_GROUPS_CLAIM = env_str("PANIC_OIDC_GROUPS_CLAIM", "groups")
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
PANIC_LDAP_GROUP_BASE_DN = env_str("PANIC_LDAP_GROUP_BASE_DN", "")
PANIC_LDAP_GROUP_FILTER = env_str("PANIC_LDAP_GROUP_FILTER", "(member={user_dn})")
PANIC_LDAP_GROUP_NAME_ATTR = env_str("PANIC_LDAP_GROUP_NAME_ATTR", "cn")
PANIC_LDAP_TIMEOUT_S = env_int("PANIC_LDAP_TIMEOUT_S", 5)

# External group -> PANIC RBAC / Team mapping (panic_common.claim_mapping)
PANIC_RBAC_ADMIN_GROUPS = env_list("PANIC_RBAC_ADMIN_GROUPS")
PANIC_RBAC_GLOBAL_CONTRIB_GROUPS = env_list("PANIC_RBAC_GLOBAL_CONTRIB_GROUPS")
PANIC_RBAC_TEAM_CONTRIB_GROUPS = env_list("PANIC_RBAC_TEAM_CONTRIB_GROUPS")
# Comma-separated "external-group=TEAMCODE" pairs, plus an optional prefix ("panic-team-netops" -> NETOPS).
PANIC_RBAC_TEAM_GROUP_MAP = env_list("PANIC_RBAC_TEAM_GROUP_MAP")
PANIC_RBAC_TEAM_GROUP_PREFIX = env_str("PANIC_RBAC_TEAM_GROUP_PREFIX", "")

ROOT_URLCONF = "panic_server.urls"
WSGI_APPLICATION = "panic_server.wsgi.application"
APPEND_SLASH = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "panic_server",
]

MIDDLEWARE = [
    "panic_server.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Loads relational state per request and persists mutations (Stage 2).
    "panic_server.middleware.PortalStoreMiddleware",
    "panic_server.middleware.ClientIpZoneMiddleware",
    # Binds the authenticated session user to the store (Stage 3, T-S3-01).
    "panic_server.auth.middleware.PanicAuthMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "panic_sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("PANIC_SESSION_COOKIE_SECURE", IS_PROD)
SESSION_COOKIE_AGE = env_int("PANIC_SESSION_AGE_S", 8 * 3600)

# Seed canonical demo fixtures automatically when the database is empty (dev/test only by default).
PANIC_AUTO_SEED = env_bool("PANIC_AUTO_SEED", not IS_PROD)

PANIC_DB_ENGINE = env_str("PANIC_DB_ENGINE", "sqlite").lower()
if PANIC_DB_ENGINE == "sqlite":
    PANIC_SQLITE_PATH = env_str("PANIC_SQLITE_PATH", str(BASE_DIR.parent.parent.parent / ".run" / "panic.sqlite3"))
    if PANIC_SQLITE_PATH != ":memory:":
        Path(PANIC_SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
    DATABASES: dict[str, dict[str, Any]] = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": PANIC_SQLITE_PATH,
        }
    }
elif PANIC_DB_ENGINE in {"postgresql", "postgres"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env_str("PANIC_DB_NAME", "panic"),
            "USER": env_str("PANIC_DB_USER", "panic"),
            "PASSWORD": env_str("PANIC_DB_PASSWORD", ""),
            "HOST": env_str("PANIC_DB_HOST", "127.0.0.1"),
            "PORT": env_int("PANIC_DB_PORT", 5432),
            "CONN_MAX_AGE": env_int("PANIC_DB_CONN_MAX_AGE", 60),
        }
    }
else:
    raise ImproperlyConfigured(f"PANIC_DB_ENGINE must be sqlite or postgresql, got {PANIC_DB_ENGINE!r}")

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    }
]

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

LANGUAGE_CODE = "en-au"
TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = False
PANIC_TZ = env_str("PANIC_TZ", "UTC")

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK: dict[str, Any] = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}

LOGGING = logging_config(
    env_str("PANIC_LOG_LEVEL", "INFO").upper(),
    env_str("PANIC_LOG_FORMAT", "json").lower(),
)

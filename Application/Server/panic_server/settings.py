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

ROOT_URLCONF = "panic_server.urls"
WSGI_APPLICATION = "panic_server.wsgi.application"
APPEND_SLASH = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "panic_server",
]

MIDDLEWARE = [
    "panic_server.middleware.RequestIdMiddleware",
    "panic_server.middleware.ClientIpZoneMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

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

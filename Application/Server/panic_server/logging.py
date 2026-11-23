"""Structured JSON logging and request-id context (AR-3.2)."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

COMPONENT = "server"

request_id_var: ContextVar[str | None] = ContextVar("panic_request_id", default=None)

CONTEXT_FIELDS = ("zone_id", "client_ip", "target_id", "action", "error_code")

_STD_ATTRS = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)).keys()
    | {"message", "asctime", "request_id", "taskName"}
)


def get_request_id() -> str | None:
    return request_id_var.get()


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            http_request = getattr(record, "request", None)
            record.request_id = request_id_var.get() or getattr(http_request, "request_id", None)
        return True


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "component": COMPONENT,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for key in CONTEXT_FIELDS:
            if key in record.__dict__:
                out[key] = _jsonable(record.__dict__[key])
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and key not in out and not key.startswith("_"):
                out[key] = _jsonable(value)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s")


def logging_config(level: str, fmt: str) -> dict[str, Any]:
    formatter = "console" if fmt == "console" else "json"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": "panic_server.logging.RequestIdFilter"}},
        "formatters": {
            "json": {"()": "panic_server.logging.JsonFormatter"},
            "console": {"()": "panic_server.logging.ConsoleFormatter"},
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": formatter,
                "filters": ["request_id"],
            }
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            "django": {"handlers": ["stdout"], "level": level, "propagate": False},
            "django.server": {"handlers": ["stdout"], "level": "WARNING", "propagate": False},
        },
    }

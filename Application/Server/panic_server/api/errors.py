"""DRF exception handler producing the API.md §3 error envelope everywhere (AR-2.8).

``{"error_code": "<ErrorCode>", "detail": "<human text>", "fields": {...}?, ...extra}`` for every
error response under ``/api/v1/...``, including DRF's own default 400/401/403/404/405 shapes
(which default to ``{"detail": "..."}``) and the store's domain exceptions
(``panic_server.store.errors``). Registered as ``REST_FRAMEWORK["EXCEPTION_HANDLER"]``.

Also supplies ``not_found_view`` -- the root URLconf's ``handler404`` -- so an unmatched path
under ``/api/...`` (never reaching DRF's own dispatch at all) still answers with this envelope
rather than Django's default HTML 404 page (API.md §1: "unknown path -> 404 NOT_FOUND").
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response

from panic_common.errors import ErrorCode
from panic_server.store import errors as store_errors
from panic_server.store.client import is_transient

#: ``APIException`` subtype -> ``ErrorCode``, most specific first. Anything not listed here (a
#: generic ``APIException``/``ValidationError``) falls back to ``VALIDATION_ERROR``.
_DRF_EXCEPTION_CODES: tuple[tuple[type[Exception], ErrorCode], ...] = (
    (drf_exceptions.NotAuthenticated, ErrorCode.UNAUTHENTICATED),
    (drf_exceptions.AuthenticationFailed, ErrorCode.UNAUTHENTICATED),
    (drf_exceptions.PermissionDenied, ErrorCode.PERMISSION_DENIED),
    (drf_exceptions.NotFound, ErrorCode.NOT_FOUND),
    (drf_exceptions.Throttled, ErrorCode.RATE_LIMITED),
    (drf_exceptions.MethodNotAllowed, ErrorCode.VALIDATION_ERROR),
    (drf_exceptions.ParseError, ErrorCode.VALIDATION_ERROR),
    (drf_exceptions.NotAcceptable, ErrorCode.VALIDATION_ERROR),
    (drf_exceptions.UnsupportedMediaType, ErrorCode.VALIDATION_ERROR),
    (drf_exceptions.ValidationError, ErrorCode.VALIDATION_ERROR),
)


class ApiError(drf_exceptions.APIException):
    """Raise directly from a view or service for a specific ``(status, error_code, detail)``.

    The cleanest shape for "my own domain exception with a precise envelope" (vs. reusing one of
    DRF's built-in ``APIException`` subtypes, which only cover generic HTTP semantics).
    """

    def __init__(self, error_code: ErrorCode, detail: str, status_code: int = 400, **extra: Any) -> None:
        self.error_code = error_code
        self.extra = extra
        self.status_code = status_code
        super().__init__(detail)


def _envelope(error_code: ErrorCode, detail: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"error_code": str(error_code), "detail": detail}
    body.update(extra)
    return body


def _code_for(exc: drf_exceptions.APIException) -> ErrorCode:
    for exc_type, code in _DRF_EXCEPTION_CODES:
        if isinstance(exc, exc_type):
            return code
    return ErrorCode.VALIDATION_ERROR


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """``REST_FRAMEWORK["EXCEPTION_HANDLER"]``: every exception type a view can raise, one shape out."""
    if isinstance(exc, ApiError):
        return Response(_envelope(exc.error_code, str(exc.detail), **exc.extra), status=exc.status_code)

    # Mirror DRF's own default handler's Http404/PermissionDenied normalisation (it only runs
    # inside that default function, which this replaces) plus our store-layer exceptions.
    if isinstance(exc, store_errors.NotFound):
        exc = drf_exceptions.NotFound("Not found.")
    elif isinstance(exc, store_errors.VersionConflict):
        return Response(
            _envelope(ErrorCode.VERSION_CONFLICT, "The resource changed since you loaded it."), status=409
        )
    elif isinstance(exc, store_errors.DuplicateKey):
        return Response(_envelope(ErrorCode.VALIDATION_ERROR, "Duplicate value."), status=400)
    elif isinstance(exc, Http404):
        exc = drf_exceptions.NotFound(str(exc) or "Not found.")
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied(str(exc) or "Permission denied.")

    if isinstance(exc, drf_exceptions.APIException):
        # Imported lazily: at module-import time ``rest_framework.views`` may itself still be
        # mid-import (it is what resolves ``REST_FRAMEWORK["EXCEPTION_HANDLER"]``/
        # ``DEFAULT_AUTHENTICATION_CLASSES`` eagerly via ``rest_framework.schemas``), so a
        # top-level import here is circular.
        from rest_framework.views import exception_handler as drf_default_exception_handler

        response = drf_default_exception_handler(exc, context)
        if response is None:  # pragma: no cover - drf_default_exception_handler always handles APIException
            return None
        code = _code_for(exc)
        # DRF's own default handler always wraps a bare APIException's ``.detail`` as
        # ``{"detail": ...}`` -- that is *not* a serializer's per-field validation errors, just
        # its generic single-message shape, so it must become the envelope's ``detail`` text
        # (not ``fields``). Only a genuine ``ValidationError`` raised *from a serializer*
        # (``serializer.is_valid(raise_exception=True)``) carries real field-name keys (or a
        # ``non_field_errors`` list) here.
        detail = response.data
        fields: dict[str, list[str]] | None = None
        human: str
        if isinstance(detail, dict) and set(detail.keys()) == {"detail"}:
            human = str(detail["detail"])
        elif isinstance(detail, dict):
            fields = {k: (v if isinstance(v, list) else [v]) for k, v in detail.items()}
            human = "Validation failed."
        elif isinstance(detail, list):
            human = "; ".join(str(d) for d in detail)
        else:
            human = str(detail)
        body = _envelope(code, human)
        if fields:
            body["fields"] = fields
        response.data = body
        return response

    if is_transient(exc):
        return Response(
            _envelope(ErrorCode.DATABASE_UNAVAILABLE, "The database is temporarily unavailable."), status=503
        )

    # Unknown error: let Django's own 500 handling take over (logged by the WSGI server / Sentry
    # equivalent elsewhere); returning None here is exactly what DRF's own handler does too.
    return None


def not_found_view(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    """``handler404`` for the root URLconf: an unmatched path never reaches DRF's own dispatch."""
    return JsonResponse(_envelope(ErrorCode.NOT_FOUND, "Not found."), status=404)


__all__ = ["ApiError", "exception_handler", "not_found_view"]

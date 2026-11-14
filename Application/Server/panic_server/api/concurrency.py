"""``If-Match`` / optimistic-concurrency helpers shared by every mutation view (T-S6-07, API.md §2).

Dashboards and endpoint lists *require* ``If-Match`` on ``PUT``/``PATCH``/``DELETE`` (missing ->
``428 PRECONDITION_REQUIRED``); every other resource treats it as optional, honoured when sent.
Either way, once a write loses the race (``panic_server.store.errors.VersionConflict``), the
response must carry the *current* ``version`` so the client can reload (API.md §2/§3) -- that
value is not on the exception itself (it only knows the stale, expected version), so callers
re-fetch the live document and raise :func:`version_conflict` with it. This is a narrow,
view-layer alternative to widening ``panic_server.api.errors``'s shared exception handler: no
repo call anywhere needs a second round trip on the *happy* path, only on an actual conflict.
"""

from __future__ import annotations

from rest_framework.request import Request

from panic_common.errors import ErrorCode
from panic_server.api.errors import ApiError

_PRECONDITION_DETAIL = "If-Match is required for this resource. Fetch it first, then retry with the current version."
_IF_MATCH_FORMAT_DETAIL = 'If-Match must be the resource\'s version, e.g. "3".'


def _parse_version(raw: str) -> int:
    value = raw.strip().strip('"')
    try:
        return int(value)
    except ValueError as e:
        raise ApiError(ErrorCode.PRECONDITION_REQUIRED, _IF_MATCH_FORMAT_DETAIL, status_code=428) from e


def expected_version(request: Request, current_version: int, *, required: bool) -> int:
    """The CAS ``expected_version`` to write with: the parsed ``If-Match`` header, or (when not
    ``required`` and no header was sent) ``current_version`` as already known by the caller."""
    header = request.headers.get("If-Match")
    if not header:
        if required:
            raise ApiError(ErrorCode.PRECONDITION_REQUIRED, _PRECONDITION_DETAIL, status_code=428)
        return current_version
    return _parse_version(header)


def version_conflict(current_version: int) -> ApiError:
    """``409 VERSION_CONFLICT`` carrying the resource's fresh ``current_version`` (API.md §2)."""
    return ApiError(
        ErrorCode.VERSION_CONFLICT,
        "The resource changed since you loaded it.",
        status_code=409,
        current_version=current_version,
    )


__all__ = ["expected_version", "version_conflict"]

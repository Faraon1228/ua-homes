"""Privacy-first, optional Sentry configuration for the UA-Dim API."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

LOGGER = logging.getLogger(__name__)
_REDACTED = "[Filtered]"
_SENSITIVE_PARTS = (
    "authorization",
    "cookie",
    "csrf",
    "password",
    "passwd",
    "secret",
    "token",
    "phone",
    "email",
    "message",
    "upload",
    "file",
    "attachment",
    "address",
    "name",
    "user",
    "contact",
    "location",
)
_EXPECTED_EXCEPTION_TYPES = {
    "BadRequest",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "MethodNotAllowed",
    "Conflict",
    "UnprocessableEntity",
    "TooManyRequests",
    "ValidationError",
    "ApiError",
    "AuthenticationError",
    "RateLimitExceeded",
}


def _sample_rate(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        rate = float(raw)
    except ValueError:
        LOGGER.warning("%s is invalid; using conservative default", name)
        return default
    if not 0 <= rate <= 1:
        LOGGER.warning("%s is outside 0..1; using conservative default", name)
        return default
    return rate


def _sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    if normalized in {"user_agent", "filename", "logger_name", "transaction_name"}:
        return False
    components = set(normalized.split("_"))
    return any(part == normalized or part in components for part in _SENSITIVE_PARTS)


def _scrub(value: Any, *, parent: str = "") -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (_REDACTED if _sensitive_key(key) else _scrub(item, parent=str(key)))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item, parent=parent) for item in value]
    return value


def _safe_url(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _REDACTED
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _status_code(event: Mapping[str, Any]) -> int | None:
    candidates = [
        event.get("tags", {}).get("http.status_code") if isinstance(event.get("tags"), Mapping) else None,
        event.get("contexts", {}).get("response", {}).get("status_code")
        if isinstance(event.get("contexts"), Mapping)
        and isinstance(event.get("contexts", {}).get("response"), Mapping)
        else None,
    ]
    for candidate in candidates:
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _is_expected_event(event: Mapping[str, Any], hint: Mapping[str, Any] | None) -> bool:
    if hint:
        exc_info = hint.get("exc_info")
        if isinstance(exc_info, tuple) and len(exc_info) >= 2:
            exception = exc_info[1]
            code = getattr(exception, "code", None)
            if isinstance(code, int) and 400 <= code < 500:
                return True
            if type(exception).__name__ in _EXPECTED_EXCEPTION_TYPES:
                return True

    status = _status_code(event)
    if status is not None and 400 <= status < 500:
        return True
    values = event.get("exception", {}).get("values", []) if isinstance(event.get("exception"), Mapping) else []
    return any(
        isinstance(item, Mapping) and item.get("type") in _EXPECTED_EXCEPTION_TYPES
        for item in values
    )


def _strip_exception_frame_vars(event: Mapping[str, Any]) -> None:
    exception = event.get("exception")
    if not isinstance(exception, Mapping):
        return
    values = exception.get("values")
    if not isinstance(values, list):
        return
    for value in values:
        if not isinstance(value, Mapping):
            continue
        stacktrace = value.get("stacktrace")
        if not isinstance(stacktrace, Mapping):
            continue
        frames = stacktrace.get("frames")
        if not isinstance(frames, list):
            continue
        for frame in frames:
            if isinstance(frame, dict):
                frame.pop("vars", None)


def before_send(event: dict[str, Any], hint: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop expected client failures and remove request/user PII."""
    if _is_expected_event(event, hint):
        return None

    _strip_exception_frame_vars(event)
    event.pop("user", None)
    request = event.get("request")
    if isinstance(request, dict):
        request["url"] = _safe_url(request.get("url"))
        request["query_string"] = ""
        request["cookies"] = _REDACTED
        if "data" in request:
            request["data"] = _scrub(request["data"])
        if isinstance(request.get("headers"), Mapping):
            request["headers"] = _scrub(request["headers"])
        if isinstance(request.get("env"), Mapping):
            request["env"] = _scrub(request["env"])

    if isinstance(event.get("extra"), Mapping):
        event["extra"] = _scrub(event["extra"])
    if isinstance(event.get("contexts"), Mapping):
        event["contexts"] = _scrub(event["contexts"])
    for breadcrumb in event.get("breadcrumbs", {}).get("values", []):
        if not isinstance(breadcrumb, dict):
            continue
        if isinstance(breadcrumb.get("data"), Mapping):
            breadcrumb["data"] = _scrub(breadcrumb["data"])
        category = str(breadcrumb.get("category", "")).lower()
        if any(part in category for part in ("auth", "http", "request", "upload", "input")):
            breadcrumb["message"] = _REDACTED
    return event


def before_send_transaction(event: dict[str, Any], _hint: dict[str, Any] | None) -> dict[str, Any] | None:
    request = event.get("request", {})
    path = urlsplit(str(request.get("url", ""))).path if isinstance(request, Mapping) else ""
    if path in {"/api/health", "/api/alerts/dispatch/health"}:
        return None
    return before_send(event, None)


def monitoring_state() -> dict[str, Any]:
    enabled = bool(os.environ.get("SENTRY_DSN", "").strip())
    return {
        "provider": "sentry",
        "enabled": enabled,
        "environment": (
            os.environ.get("SENTRY_ENVIRONMENT")
            or os.environ.get("RAILWAY_ENVIRONMENT_NAME")
            or os.environ.get("ENVIRONMENT")
            or "development"
        ),
        "release_configured": bool(
            os.environ.get("SENTRY_RELEASE") or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        ),
    }


def initialize_sentry() -> bool:
    """Initialize Sentry only when a DSN is configured; missing config is healthy."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    state = monitoring_state()
    sentry_sdk.init(
        dsn=dsn,
        environment=state["environment"],
        release=os.environ.get("SENTRY_RELEASE") or os.environ.get("RAILWAY_GIT_COMMIT_SHA") or None,
        integrations=[FlaskIntegration(transaction_style="url")],
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=_sample_rate("SENTRY_TRACES_SAMPLE_RATE", 0.01),
        profiles_sample_rate=_sample_rate("SENTRY_PROFILES_SAMPLE_RATE", 0.0),
        before_send=before_send,
        before_send_transaction=before_send_transaction,
        max_breadcrumbs=50,
    )
    return True


def bind_request_context(request_id: str, method: str, route: str) -> None:
    if not monitoring_state()["enabled"]:
        return
    import sentry_sdk

    sentry_sdk.set_tag("request_id", request_id)
    sentry_sdk.set_tag("http.method", method)
    sentry_sdk.set_context("ua_request", {"request_id": request_id, "route": route})

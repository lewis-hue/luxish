"""Request-scoped observability: request IDs and structured, redacted logging."""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_MAX_LENGTH = 64
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

#: Dropped from every log record, at any nesting depth. The first five are the
#: set named by the plan; the remainder are the same classes of secret.
REDACTED_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "access_token",
        "refresh_token",
        "latitude",
        "longitude",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "id_token",
        "identity_token",
        "session_token",
        "token_hash",
        "password",
        "api_key",
        "meta_api_key",
        "secret",
    }
)

_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}

_MAX_REDACT_DEPTH = 6


def new_request_id() -> str:
    return uuid.uuid4().hex


def normalise_request_id(raw: str | None) -> str:
    """Echo a caller-supplied ID only when it is short and boring.

    An inbound header is attacker-controlled: echoing it unvalidated puts
    arbitrary bytes into our logs and response headers.
    """
    if raw and _SAFE_REQUEST_ID.match(raw):
        return raw
    return new_request_id()


class RedactionFilter(logging.Filter):
    """Drops sensitive keys and raw image bytes before anything is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        dropped: list[str] = []
        for key in list(record.__dict__):
            if key in _STANDARD_RECORD_FIELDS:
                continue
            if key.lower() in REDACTED_KEYS:
                delattr(record, key)
                dropped.append(key)
                continue
            setattr(record, key, _scrub(getattr(record, key), dropped, 0))
        record.redacted = dropped
        return True


def _scrub(value: Any, dropped: list[str], depth: int) -> Any:
    if depth > _MAX_REDACT_DEPTH:
        return "<truncated>"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes len={len(value)}>"
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in REDACTED_KEYS:
                dropped.append(k)
                continue
            out[k] = _scrub(v, dropped, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return type(value)(_scrub(v, dropped, depth + 1) for v in value)
    return value


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line, with request-scoped context attached."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key == "redacted":
                continue
            payload[key] = value
        if "request_id" not in payload:
            rid = request_id_ctx.get()
            if rid:
                payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Binds a request ID to the context and echoes it on every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = normalise_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

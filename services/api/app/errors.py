"""Structured API errors.

Every failure a client is expected to branch on carries a stable ``code``;
``message`` is for humans and may change.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.middleware import request_id_ctx


class ApiError(Exception):
    """Rendered as ``{code, message, detail?, request_id?}``."""

    status_code: int = 400
    code: str = "bad_request"
    default_message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        status_code: int | None = None,
        code: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.detail = detail or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            payload["detail"] = self.detail
        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id
        return payload


class NotFound(ApiError):
    status_code = 404
    code = "not_found"
    default_message = "Not found."


class Unauthenticated(ApiError):
    status_code = 401
    code = "unauthenticated"
    default_message = "A valid session is required."


class Conflict(ApiError):
    status_code = 409
    code = "conflict"
    default_message = "The request conflicts with current state."


class PayloadTooLarge(ApiError):
    status_code = 413
    code = "payload_too_large"
    default_message = "The declared payload exceeds the permitted size."


class UnsupportedMediaType(ApiError):
    status_code = 415
    code = "unsupported_media_type"
    default_message = "The declared content type is not accepted."


class CapabilityUnavailable(ApiError):
    """A capability this build does not implement. Labelled, never faked."""

    status_code = 503
    code = "capability_unavailable"
    default_message = "That capability is not available in this build."


def _why(exc: RequestValidationError) -> str:
    """The first validation failure, as a sentence naming the field.

    **"Request validation failed." was the whole message.** The
    details were in the body all along, under `errors`, and the
    client shows the message - so a rejected save read as an
    unexplained refusal. A real one: the taste screen offered "Pick
    any" occasions against a schema that stopped at six, and the
    only thing on screen was the framework's own string.

    One error, not all of them: the first is the one to fix, and a
    list of five is a wall nobody reads. The full set stays in
    `errors` for whoever is debugging.
    """
    problems = exc.errors() or []
    if not problems:
        return "Request validation failed."
    first = problems[0]
    # `loc` is ("body", "occasions", 3); the field is the part after
    # the source, and the index is noise in a sentence.
    where = [
        str(part)
        for part in (first.get("loc") or ())
        if isinstance(part, str) and part not in ("body", "query", "path")
    ]
    said = str(first.get("msg") or "is not valid").strip()
    if not where:
        return f"{said[:1].upper()}{said[1:]}."
    return f"{'.'.join(where)}: {said}."


def _error_body(code: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if detail:
        body["detail"] = detail
    request_id = request_id_ctx.get()
    if request_id:
        body["request_id"] = request_id
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(exc.to_payload()))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(_error_body(code, str(exc.detail))),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                _error_body(
                    "invalid_request",
                    _why(exc),
                    {"errors": exc.errors()},
                )
            ),
        )

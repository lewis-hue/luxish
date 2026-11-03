"""Consent request and response shapes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


class ConsentSetIn(BaseModel):
    #: The whole request. Granting and withdrawing differ by this and nothing
    #: else, because a consent that is harder to withdraw than to give was
    #: never freely given.
    granted: bool
    #: What asked. Recorded so a screen can later say where a grant came from.
    source: Annotated[str | None, Field(max_length=64)] = None


class ConsentOut(BaseModel):
    kind: str
    granted: bool
    #: Null when never granted. A client should show "never asked" and
    #: "withdrawn" differently: one is a question not yet put to someone, the
    #: other is their answer.
    granted_at: datetime | None = None
    revoked_at: datetime | None = None


class ConsentsResponse(BaseModel):
    items: list[ConsentOut]


__all__ = ["ConsentOut", "ConsentSetIn", "ConsentsResponse"]

"""What an export looks like to the client.

Deliberately no download URL on the row. The client builds the path
from the id, which keeps the one place that decides who may read the
bytes on the server - a URL handed out in a payload is a URL somebody
will eventually treat as the permission.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ExportOut(BaseModel):
    id: uuid.UUID
    #: `gathering`, `ready`, `failed` or `expired`.
    state: str
    #: Null until it is ready.
    byte_size: int | None = None
    #: How many of their pictures went in, and how many did not.
    #:
    #: Sent to the client because the screen says it. An archive that
    #: left pictures out is still worth downloading, and somebody has
    #: to be told so they can ask for another to get the rest.
    pictures_included: int = 0
    pictures_omitted: int = 0
    #: Why it failed, in the owner's terms. Null unless it did.
    failure: str | None = None
    #: When the download stops working.
    expires_at: datetime | None = None
    created_at: datetime


__all__ = ["ExportOut"]

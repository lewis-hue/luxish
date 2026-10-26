"""External content references (ADR-009).

What a pasted Instagram / TikTok / Pinterest link becomes: a canonical URL, the
platform, the author handle when the URL carries one, and when we saw it.

There is no column for downloaded bytes, because we do not download platform
media. ``media_downloaded`` exists as a permanent, queryable assertion that we
did not — if it ever becomes true, that is a bug with a name.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

SOCIAL_PLATFORMS = ("instagram", "tiktok", "pinterest", "youtube", "other")

social_platform_enum = named_enum("social_platform", *SOCIAL_PLATFORMS)


class ExternalReference(Base, TimestampMixin):
    __tablename__ = "external_references"
    __table_args__ = (
        # One reference per user per link: pasting twice is not two references.
        sa.UniqueConstraint(
            "user_id", "canonical_url", name="uq_external_references_user_id_canonical_url"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    platform: Mapped[str] = mapped_column(social_platform_enum, nullable=False)
    canonical_url: Mapped[str] = mapped_column(sa.String(2048), nullable=False)
    submitted_url: Mapped[str] = mapped_column(sa.String(2048), nullable=False)
    author_handle: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    note: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    #: When the user handed us the link. Not a fetch timestamp — we do not fetch.
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    #: The capability record in force when this reference was stored, so a later
    #: change of policy does not rewrite history.
    capability_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    #: Always false. See the module docstring.
    media_downloaded: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

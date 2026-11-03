"""What the clothes in a posted fit are, read off the photograph.

**Its own table, not columns on `posts`.** A description is derived data: it
has a model behind it, a prompt version, and a reason to be recomputed. The
author's caption is theirs and lives on their row; this sits alongside and
never overwrites it. The same separation the garment studio keeps between a
photograph somebody took and a shot generated from it.

**One row per post, replaced in place.** Re-reading a photograph should
correct the description rather than accumulate versions of it, and the
version that produced the current words is on the row, so a later prompt
change can find every row that predates it.

**The generated caption is a suggestion, never a publication.** It is
offered where the author wrote nothing, and a client renders it as the
description it is. Silently replacing somebody's words with a model's would
be the one thing a captioning feature must not do.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_pk
from app.db.types import UTCDateTime


class FitDescriptionRow(Base, TimestampMixin):
    __tablename__ = "post_descriptions"

    #: The post, and the primary key: one description per fit, replaced
    #: rather than versioned.
    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    #: The whole outfit in one sentence. This is what a try-on puts on the
    #: asker's avatar, so it is the field everything else depends on.
    outfit: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    #: A caption naming the main pieces. Shown where the author wrote none.
    caption: Mapped[str | None] = mapped_column(sa.String(140), nullable=True)
    #: Each garment as named: ``[{"name", "colour", "category"}]``. Rides
    #: with a try-on so the finished picture can be labelled without
    #: paying a second model call to re-read what was just asked for.
    pieces: Mapped[list[dict[str, Any]]] = mapped_column(
        sa.JSON(), nullable=False, default=list
    )
    #: Which model and wording produced this, so a prompt change can find
    #: the rows that predate it.
    model: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)


__all__ = ["FitDescriptionRow"]


class FitPieceRow(Base):
    """One garment, cut out of the photograph it was worn in.

    **A row rather than an id in the description's JSON.** Media
    readability here is decided by a live join - "does a post that
    is published right now carry this" - so that there is no flag
    anywhere to forget to clear. An id living only inside a JSON
    blob cannot be joined, and the gate would have ended up trusting
    a flag of its own instead. An id nobody can join is an id nobody
    checks.

    The taxonomy facts are copied from the description beside it so
    a client can label a cut-out without reading that JSON too. The
    free-text name an author typed never travels here, for the same
    reason it never travels anywhere else.
    """

    __tablename__ = "post_description_pieces"
    __table_args__ = (
        sa.UniqueConstraint(
            "post_id", "position", name="uq_post_description_pieces_post_position"
        ),
        sa.Index("ix_post_description_pieces_post", "post_id", "position"),
        sa.Index("ix_post_description_pieces_asset", "media_asset_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Where it sits in the outfit, matching the described order.
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    colour: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    category: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )

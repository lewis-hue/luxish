"""What a photograph is of, read off the photograph.

**Its own table, not a column on `posts`.** This is derived data with
a model and a prompt version behind it, and a reason to be
recomputed - the same separation `post_descriptions` already keeps
between what an author wrote and what a machine read. A column on
`posts` would make a machine's guess look like part of the author's
row.

**One row per post, replaced in place.** Re-reading a photograph
should correct the reading rather than accumulate versions of it, and
`model` plus `prompt_version` on the row are what let a later change
find every row that predates it.

**The vector is stored as JSON, not as a pgvector column.** At this
corpus size the nearest-neighbour search is a scan over a few hundred
unit vectors, which is microseconds of arithmetic - an index would be
machinery with nothing to do. ADR-004 scopes pgvector to "where
measured retrieval needs justify it", and the honest trigger here is
when a scan stops being fast enough, not when the table exists. The
`model` column is what makes that migration possible rather than a
guess: a mixed table can be rebuilt one model at a time.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PostVisionRow(Base, TimestampMixin):
    __tablename__ = "post_vision"

    #: The post, and the primary key: one reading per pin.
    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    #: Which photograph was read.
    #:
    #: Pinned, like the description's is, because a cover can be
    #: reshaped after the job is queued and a reading of a rotated
    #: photograph describes a person lying down.
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: One of `app.domain.discovery.subject.SUBJECTS`. The gate.
    subject: Mapped[str] = mapped_column(sa.String(24), nullable=False)

    #: How sure the model was about `subject`, 0-1.
    confidence: Mapped[float] = mapped_column(
        sa.Float(), nullable=False, default=1.0
    )

    #: The descriptive facets it recognised, from the closed list.
    facets: Mapped[list[str]] = mapped_column(
        sa.JSON(), nullable=False, default=list
    )

    #: The unit vector built from the above. Fixed length per model.
    vector: Mapped[list[float]] = mapped_column(
        sa.JSON(), nullable=False, default=list
    )

    #: One short phrase for the "why am I seeing this" line.
    #:
    #: Never rendered where an author's caption goes. It is a
    #: machine's description of their photograph, and this app
    #: already holds that line for `post_descriptions`.
    note: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)

    #: Which model and prompt produced this, so a change can find
    #: every row that predates it.
    model: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    def as_pair(self) -> tuple[str, list[float]]:
        """`(subject, vector)`, the shape the ranker wants."""
        return self.subject, list(self.vector or [])

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<PostVision {self.post_id} {self.subject}>"


def readings_by_post(rows: list[PostVisionRow]) -> dict[uuid.UUID, Any]:
    """Keyed for the ranker, which wants a dict rather than a list."""
    return {row.post_id: row.as_pair() for row in rows}


__all__ = ["PostVisionRow", "readings_by_post"]

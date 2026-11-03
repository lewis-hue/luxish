"""A brand story: one product, several frames, asked for together.

**The story owns the brief, the frames own the scene.** A brand writes its
direction once and gets a set back, so the brief is on the story and each
frame records only which scene it is. That also makes the stored record
honest about what was asked: one direction, several readings of it.

**The frames are `garment_shots`.** A brand frame is an edit of a
photograph the brand owns, which is exactly what a studio shot already is -
same ownership check, same billing, same storage, same tombstone. What the
story adds is grouping and order. Reusing the row rather than copying its
shape means a frame cannot drift out of step with a shot.

**A reference fit is stored by id and by the words read from it.** Both,
deliberately: the id is the provenance, and the note is what actually went
into the prompt. Keeping only the id would make a frame impossible to
explain once the post was withdrawn; keeping only the note would lose who
it came from.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

STORY_STATES: tuple[str, ...] = ("working", "ready", "partial", "failed")

story_state_enum = named_enum("brand_story_state", *STORY_STATES)


class BrandStory(Base, TimestampMixin):
    __tablename__ = "brand_stories"
    __table_args__ = (
        sa.Index("ix_brand_stories_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: Which ready-made set this is, or ``custom`` for a hand-picked list.
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    #: What the brand called it. Their words.
    title: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    #: The brand's own direction, as typed, before it was composed into
    #: prompts. Stored so a story can be explained and re-run.
    brief: Mapped[str | None] = mapped_column(sa.String(600), nullable=True)
    #: The cast the brand chose, as a mapping of the closed vocabularies in
    #: ``app.workers.brand_studio.CAST_OPTIONS``. Empty means unspecified,
    #: which means the edit decided.
    cast: Mapped[dict[str, str]] = mapped_column(
        sa.JSON(), nullable=False, default=dict
    )
    #: A published fit used as a styling reference, if there was one. SET
    #: NULL rather than CASCADE: a withdrawn post should not delete the
    #: brand's own finished frames.
    reference_post_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: The words read off that reference, which is what the prompt carried.
    #: The reference cannot be a second input image, so this is the whole
    #: of its influence and the API says so.
    style_note: Mapped[str | None] = mapped_column(sa.String(400), nullable=True)
    state: Mapped[str] = mapped_column(
        story_state_enum, nullable=False, default="working", server_default="working"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, index=True
    )


__all__ = ["BrandStory", "STORY_STATES"]

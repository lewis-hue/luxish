"""Moodboards: named boards, and the fits pinned to them.

**Distinct from saving, and the distinction is the point.** Saving is "I
like this"; pinning is "this belongs with these others". One is a verdict
on a single fit, the other is an argument about several. Collapsing them
would mean either that saving something files it somewhere (so there is no
way to simply like a thing) or that a board is just a filtered view of
likes (so there is no way to put two things together without liking both).

**A pin references content by id, never by URL.** `post_id` points at a
fit somebody published here, whose photograph lives in the media pipeline
that already owns ownership and consent. Nothing here stores an image, and
nothing here may: the repository rule is that no code downloads Instagram,
third-party platform media, and that analysis runs on user-supplied media
only. A pin that wanted to hold an outside picture would need that picture
uploaded first, which is the point.

**Order is explicit.** A board is a composition — the arrangement is part of
what somebody made — so position is a column rather than an accident of
insertion time.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_fk, uuid_pk


class Moodboard(Base, TimestampMixin):
    __tablename__ = "moodboards"
    __table_args__ = (
        # Two boards with the same name are two boards nobody can tell apart.
        sa.UniqueConstraint("user_id", "name", name="uq_moodboards_user_name"),
        sa.Index("ix_moodboards_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: What somebody called it. Their words, never generated.
    name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    #: A line about what the board is for. Optional.
    note: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)


class MoodboardPin(Base, TimestampMixin):
    __tablename__ = "moodboard_pins"
    __table_args__ = (
        # Pinning the same fit twice to one board is pinning it once.
        sa.UniqueConstraint(
            "moodboard_id", "post_id", name="uq_moodboard_pins_board_post"
        ),
        sa.Index("ix_moodboard_pins_board_position", "moodboard_id", "position"),
        sa.Index("ix_moodboard_pins_post", "post_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    moodboard_id: Mapped[uuid.UUID] = uuid_fk("moodboards.id")
    #: The fit on the board. A real foreign key: a post is this app's own
    #: row, so a deleted post takes its pins with it rather than leaving a
    #: tile that renders nothing.
    #:
    #: A pin used to be either this or a curated look's string id, with a
    #: check constraint enforcing exactly one. The catalogue is gone, so a
    #: pin is a fit and the column can simply be required.
    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False
    )
    #: Where it sits. A board is a composition, so this is a column rather
    #: than an accident of insertion order.
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    @property
    def ref(self) -> str:
        """The pin, as the one string arrangement and removal are keyed on."""
        return str(self.post_id)

"""One avatar picture that was asked for: its state, and what is in it.

Exists because drawing an avatar is a **27-second paid model call**, and it
was being made inside a request handler. Every other model call in this
service goes through a durable job for reasons ADR-005 and ADR-013 already
record — Cloud Run request timeouts, a connection held open for half a
minute, and no record of the work if the process dies mid-call. The avatar
was the one exception, and it was an oversight rather than a decision.

**The row is created before the work starts.** That is what makes the job
durable: the record of "this person asked for a picture" exists whether or
not the worker, the broker or the model survives the next thirty seconds. A
render that fails is a row that says so, not a request that timed out.

**`pieces` is written from what was asked for, never re-detected.** When the
avatar is dressed in an outfit, the garments are already known exactly — they
came from that look. Running a vision model over the result to find out what
we just requested would pay to guess at something already in hand, which is
the same mistake the categorise-versus-detect race was.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONB, Base, TimestampMixin, named_enum, uuid_fk, uuid_pk

#: What was asked for.
#: ``base`` is drawn from what somebody said about themselves.
#: ``from_photo`` is drawn from a photograph they uploaded of themselves,
#: which is a different thing and worth telling apart: one is a figure
#: invented to a description, the other is a likeness.
RENDER_KINDS: tuple[str, ...] = ("base", "try_on", "from_photo")

#: Where it got to.
#:
#: Mirrors the job states rather than inventing a parallel vocabulary: a
#: render is a thin record over one job, and two words for the same condition
#: is how a screen ends up reporting a state the job never had.
RENDER_STATES: tuple[str, ...] = ("queued", "running", "ready", "failed")

render_kind_enum = named_enum("avatar_render_kind", *RENDER_KINDS)
render_state_enum = named_enum("avatar_render_state", *RENDER_STATES)


class AvatarRender(Base, TimestampMixin):
    __tablename__ = "avatar_renders"
    __table_args__ = (
        # The read is always "this person's renders, newest first".
        sa.Index("ix_avatar_renders_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    kind: Mapped[str] = mapped_column(render_kind_enum, nullable=False)
    state: Mapped[str] = mapped_column(
        render_state_enum, nullable=False, default="queued", server_default="queued"
    )

    #: The job doing the work, so a stuck render can be traced to it.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    #: The picture, once there is one.
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: The photograph this likeness was drawn from, for a `from_photo`
    #: render. SET NULL rather than CASCADE: removing the source must not
    #: silently destroy pictures somebody chose to keep, and keeping the
    #: link is what makes "delete the photo of my face" able to find them.
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: What the person said about themselves alongside the photograph,
    #: in their own words. Theirs: nothing here is read off the picture.
    note: Mapped[str | None] = mapped_column(sa.String(400), nullable=True)

    #: The published fit this was dressed in, when somebody tapped "Try it
    #: on" under another person's photograph. SET NULL rather than CASCADE:
    #: a withdrawn post must not delete a picture of this person.
    source_post_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: The sentence the model was given. Kept so a picture can be explained.
    outfit: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    #: The garments in the picture, as they were requested.
    #:
    #: `[{"name": ..., "colour": ..., "category": ...}]`. This is what makes
    #: a render tappable: every piece can be labelled and searched for
    #: without a second model call, because it was never a guess.
    pieces: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)

    #: Why it failed, in the words the failure used. Null unless `failed`.
    error: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)

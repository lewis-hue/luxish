"""Studio shots: what a garment looks like somewhere other than a hanger.

A shot hangs off a **photograph**, not off a wardrobe item. The stylist can
be handed a picture from the camera roll and asked to shoot it, and that
picture never becomes a garment — so `source_asset_id` is required and
`garment_id` is the optional provenance.

One row per result, pointing at the garment it came from and the media
asset it was written to. The treatment is stored as a plain string rather
than an enum: the set of treatments is prompt wording, which changes far
more often than a schema should, and a row naming a treatment that has
since been reworded is still a true record of what was run.

Tombstoned rather than deleted, like every other user-owned row here, so
a discarded shot does not take its storage object with it until the sweep
runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, named_enum, uuid_fk, uuid_pk

SHOT_STATES: tuple[str, ...] = ("queued", "running", "ready", "failed")

shot_state_enum = named_enum("garment_shot_state", *SHOT_STATES)


class GarmentShot(Base, TimestampMixin):
    __tablename__ = "garment_shots"
    __table_args__ = (
        sa.Index("ix_garment_shots_garment_id_created_at", "garment_id", "created_at"),
        # "Everything this person has shot, newest first", which is how the
        # stylist lists them when there is no garment to group by.
        sa.Index("ix_garment_shots_user_id_created_at", "user_id", "created_at"),
        # A brand story reads its frames in order.
        sa.Index("ix_garment_shots_story_position", "story_id", "position"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Denormalised from the garment so ownership can be checked, and a
    #: discard authorised, without a join.
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: The photograph being edited. **This is the source of truth**, not the
    #: garment: the stylist can shoot a picture straight off somebody's
    #: phone, which has no wardrobe row behind it.
    source_asset_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Set when the shot came from a wardrobe item, so the garment's own
    #: screen can list its shots. Null for a one-off photograph.
    garment_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("garments.id", ondelete="CASCADE"),
        nullable=True,
    )
    treatment: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    #: Whether this one was asked for wide.
    #:
    #: **The exception to the app being upright everywhere.** A
    #: packshot and a cutout are forced portrait, because a flat-lay
    #: comes back wide and was otherwise the only card in the feed
    #: on its side. The studio is the tool half of the product
    #: though, and somebody making a banner has a reason to want the
    #: frame they asked for.
    #:
    #: Safe to allow: a landscape picture posted to the feed is
    #: stood upright on its way in, so this cannot put a sideways
    #: card on anybody's board.
    landscape: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    #: The exact prompt this frame was run with, when it was composed rather
    #: than chosen. Null for a garment studio shot, which runs its
    #: treatment's fixed wording; set for a brand frame, where the prompt is
    #: built from a scene, a cast, a reference and the brand's own brief, so
    #: the run can be explained and repeated after the fact.
    prompt: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    #: What the person actually typed, kept apart from the prompt it
    #: produced. Two different things: `prompt` is what was sent to the
    #: model, `brief` is the direction somebody gave in their own words.
    #: Storing only the composed prompt would mean their sentence could
    #: not be shown back to them, re-run, or edited without re-deriving
    #: it from wording it is now buried in.
    brief: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    #: The brand story this frame belongs to, if any.
    story_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("brand_stories.id", ondelete="CASCADE"),
        nullable=True,
    )
    #: Where it sits in that story. A story is a sequence, so this is a
    #: column rather than an accident of insertion order.
    position: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    state: Mapped[str] = mapped_column(
        shot_state_enum, nullable=False, default="queued", server_default="queued"
    )
    #: The job doing the work, so a stuck shot can be traced to it.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    #: Null until the edit comes back. A row with no asset is a shot still
    #: being taken, or one that failed — the state says which.
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Why it failed, in words the owner can read.
    error: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, index=True
    )

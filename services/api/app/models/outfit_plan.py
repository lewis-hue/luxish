"""What somebody plans to wear, on a date.

The app answers "what should I wear" everywhere and had nowhere to answer it
*for Thursday*. A plan is that: a date, the clothes, and optionally a line
about the occasion.

**The clothes are theirs.** A plan used to point at a curated look - a
catalogue entry nobody owned, chosen from a generated set - so planning a
week produced a wardrobe of clothes the wearer did not have. It now holds
garments out of their own wardrobe, every id re-validated against its owner
before it is stored.

**One plan per date, deliberately.** Somebody who changes for the evening has
a real case this does not cover, and the unique constraint is what makes a
plan idempotent — tapping a look twice on the same day replaces rather than
stacking. Adding a second slot per day later means relaxing the constraint and
giving the row an order, which is a smaller change than untangling duplicate
plans somebody accumulated by double-tapping.

**A date, not a timestamp.** "Thursday" is a day in the wearer's calendar, not
an instant: a plan made in Nairobi for Thursday must still be Thursday when
they land in London. Storing a timestamp would move it by a timezone.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid_fk, uuid_pk


class OutfitPlan(Base, TimestampMixin):
    __tablename__ = "outfit_plans"
    __table_args__ = (
        # One per person per day, so planning the same day twice is planning
        # it once and the client never has to know whether a row existed.
        sa.UniqueConstraint(
            "user_id", "planned_for", name="uq_outfit_plans_user_date"
        ),
        # The read is always a date range for one person: a week, a month.
        sa.Index("ix_outfit_plans_user_date", "user_id", "planned_for"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    #: The day, in the wearer's calendar. Not a timestamp; see the module docstring.
    planned_for: Mapped[date_type] = mapped_column(sa.Date, nullable=False)
    #: What this used to point at.
    #:
    #: Nullable and never written any more. Kept rather than dropped
    #: because the rows that have one are somebody's plans, and
    #: deleting the column would rewrite their history to say they
    #: planned nothing.
    #: The fit this day was planned from, when it started on one.
    #:
    #: **A plan is garments; this is what prompted it.** "Plan a day
    #: for it" starts on somebody else's pin, and a pin is not a
    #: garment - it is a photograph that gave them the idea. Without
    #: this the action arrived at an empty calendar with nothing
    #: identifying what "it" was.
    #:
    #: Null on most rows and always will be: a day planned straight
    #: out of the wardrobe references nothing. Set null rather than
    #: cascaded when the post goes, so a fit coming down costs the
    #: picture and not the plan.
    reference_post_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: What it is for. The user's own words, never generated.
    note: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    #: Whether they actually wore it.
    #:
    #: Null means not yet answered, which is different from "no". A plan for
    #: next Tuesday has not been declined; it has not happened.
    worn: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)


class OutfitPlanItem(Base):
    """One garment in a plan, in the order it was added.

    A row per garment rather than a list on the plan: the wardrobe is
    rows, and a plan referencing them by id is what makes "delete this
    jumper" take it out of every day it was planned for instead of
    leaving a name behind.
    """

    __tablename__ = "outfit_plan_items"
    __table_args__ = (
        sa.PrimaryKeyConstraint("plan_id", "garment_id"),
        sa.Index("ix_outfit_plan_items_plan", "plan_id", "position"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("outfit_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: CASCADE, so removing a garment removes it from every plan it was
    #: in. A plan naming clothes somebody no longer owns is worse than
    #: a shorter plan.
    garment_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("garments.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

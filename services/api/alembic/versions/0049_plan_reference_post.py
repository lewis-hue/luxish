"""a planned day can point at the fit it was planned from

Revision ID: 0049_plan_reference_post
Revises: 0048_message_hidden_for
Create Date: 2026-11-02

**A plan is garments; this is what prompted it.**

`outfit_plan_items` already holds what somebody intends to wear, and
those are garments out of their own wardrobe - deliberately, because
a plan naming a catalogue look produced a week of clothes the wearer
did not own.

What was missing is the other half of "plan a day for it". That
action starts on somebody else's pin, and a pin is not a garment:
it is a photograph that gave them the idea. The action therefore
arrived at an empty calendar with nothing identifying what "it" was,
and the picture they had been looking at was gone.

So the plan keeps a reference to the post. Nullable and expected to
be null on most rows: a day planned straight out of the wardrobe
references nothing, which is the ordinary case and always will be.

`ondelete="SET NULL"` rather than cascade. A fit coming down - its
author deleting it, a moderator removing it - must not take
somebody's plan for next Tuesday with it. They lose the picture that
prompted it; they keep the day and the clothes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049_plan_reference_post"
down_revision = "0048_message_hidden_for"
branch_labels = None
depends_on = None


#: Named here so the upgrade and the downgrade cannot disagree.
REFERENCE_FK = "fk_outfit_plans_reference_post_id_posts"


def upgrade() -> None:
    op.add_column(
        "outfit_plans",
        sa.Column("reference_post_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    # SQLite cannot ALTER a foreign key in, so it goes through a batch
    # operation - which rebuilds the table there and is a plain ALTER
    # on PostgreSQL, the database that ships. The same pattern as
    # `0009_wardrobe_media`.
    with op.batch_alter_table("outfit_plans") as batch:
        batch.create_foreign_key(
            REFERENCE_FK,
            "posts",
            ["reference_post_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("outfit_plans") as batch:
        batch.drop_constraint(REFERENCE_FK, type_="foreignkey")
    op.drop_column("outfit_plans", "reference_post_id")

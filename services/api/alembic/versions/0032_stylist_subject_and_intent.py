"""The assistant learns what a request is about, and what it is asking for.

The stylist screen used to carry a grid of capability tiles: shoot this on
a model, cut it out, make a lookbook. That is a menu of the backend's
functions rather than a way of asking for something, and it made the one
screen somebody talks to the busiest in the app.

The capabilities do not go away; the buttons do. A request now carries what
it is *about* - a garment, a photograph, or somebody else's published fit -
and the worker decides what is being asked for and dispatches it. These
columns are what make that possible: the subject ids so the worker has
something to act on, ``intent`` so the decision is recorded rather than
re-guessed, and ``reply`` so a run that started a shoot can say so in the
thread without pretending to be an outfit.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_stylist_subject_and_intent"
down_revision = "0031_fit_descriptions_brand_stories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stylist_runs") as batch:
        batch.add_column(sa.Column("subject_garment_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("subject_asset_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("subject_post_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("intent", sa.String(24), nullable=True))
        batch.add_column(sa.Column("reply", sa.Text(), nullable=True))
        # SET NULL throughout: a deleted garment, asset or post must leave
        # the record of what was asked intact rather than removing it.
        batch.create_foreign_key(
            "fk_stylist_runs_subject_garment",
            "garments",
            ["subject_garment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_stylist_runs_subject_asset",
            "media_assets",
            ["subject_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_stylist_runs_subject_post",
            "posts",
            ["subject_post_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("stylist_runs") as batch:
        batch.drop_constraint("fk_stylist_runs_subject_post", type_="foreignkey")
        batch.drop_constraint("fk_stylist_runs_subject_asset", type_="foreignkey")
        batch.drop_constraint("fk_stylist_runs_subject_garment", type_="foreignkey")
        batch.drop_column("reply")
        batch.drop_column("intent")
        batch.drop_column("subject_post_id")
        batch.drop_column("subject_asset_id")
        batch.drop_column("subject_garment_id")

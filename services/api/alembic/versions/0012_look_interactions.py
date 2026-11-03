"""look interactions: the population a trend can be measured over

Revision ID: 0012_look_interactions
Revises: 0011_garment_image_is_rendered
Create Date: 2026-10-28

Until this table exists, "trending" has nobody to be about. The client has
been capturing these events locally and labelling the result "Popular with
you", which is the honest name for one device's taps; this is where they
become a population.

Three constraints carry the honesty rather than the performance:

* the unique constraint makes a re-uploaded event one event, because the
  client keeps a local buffer and re-sends what it is unsure about, and a
  flaky connection should not read as enthusiasm;
* ``occurred_at`` is indexed because the aggregate is a time window, and it
  stores device time rather than arrival time so a phone that was offline for
  a day does not post its backlog as a spike;
* ``aesthetics`` is denormalised onto the row so the aggregate describes what
  a look *was* when somebody reacted to it.

``look_id`` is a string, not a foreign key. Looks are bundled content rather
than rows, so an id that stops existing should quietly drop out of the
aggregate instead of blocking a write or cascading a delete.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_look_interactions"
down_revision = "0011_garment_image_is_rendered"
branch_labels = None
depends_on = None

INTERACTION_KINDS = ("view", "search_piece", "ask_stylist", "save")


def upgrade() -> None:
    # Created explicitly, then referenced with `create_type=False`. Without
    # that flag `create_table` emits its own CREATE TYPE for the same enum and
    # the second one fails, which leaves the type behind and the table absent
    # — a half-applied revision that then refuses to re-run.
    bind = op.get_bind()
    kind: sa.types.TypeEngine
    if bind.dialect.name == "postgresql":
        kind = postgresql.ENUM(
            *INTERACTION_KINDS, name="look_interaction_kind", create_type=False
        )
        sa.Enum(*INTERACTION_KINDS, name="look_interaction_kind").create(
            bind, checkfirst=True
        )
    else:
        kind = sa.Enum(*INTERACTION_KINDS, name="look_interaction_kind")

    op.create_table(
        "look_interactions",
        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("look_id", sa.String(64), nullable=False),
        sa.Column("kind", kind, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "aesthetics",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id",
            "look_id",
            "kind",
            "occurred_at",
            name="uq_look_interactions_user_look_kind_occurred",
        ),
    )
    op.create_index(
        "ix_look_interactions_occurred_at", "look_interactions", ["occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_look_interactions_occurred_at", table_name="look_interactions")
    op.drop_table("look_interactions")
    sa.Enum(name="look_interaction_kind").drop(op.get_bind(), checkfirst=True)

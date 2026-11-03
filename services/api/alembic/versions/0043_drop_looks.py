"""The catalogue of curated looks, and everything that pointed at it

Revision ID: 0043_drop_looks
Revises: 0042_plan_garments
Create Date: 2026-11-01

A "look" was a bundled catalogue entry: content shipped with the app
rather than a row anybody owned. Nothing shows one any more - the app's
unit is a fit somebody photographed and published - so the two tables
about looks and the five columns pointing at one are dropped here.

**This drops data, and that is the intent.** `saved_looks` holds
collections people built out of the catalogue and `look_interactions`
holds their taps on it. Both describe content that no longer exists, so
keeping them would preserve a record nobody can open. The features they
fed were rebuilt on fits before this ran, not deleted: the studio
counts saves on what somebody published, the stylist's sense of what
somebody reaches for counts the fits they keep, and the inbox notice
counts other people keeping a fit.

**The columns go in two groups, for two reasons.** `posts.look_id` and
`moodboard_pins.look_id` are dropped because a fit must now have a
photograph and a pin must now name a fit - a surviving value there
would be a row the application cannot render. `outfit_plans.look_id`
and `avatar_renders.look_id` are dropped because the plan or render
already carries its real subject beside them (garments, a source post,
a source asset), so the column is dead weight rather than the only
record of what was asked for.

**`report_subject` keeps its `look` value.** A report filed against a
look is a moderation record - evidence a person may still need to read
- and narrowing the enum would make those rows unloadable. The API no
longer accepts one.

The downgrade rebuilds the tables and columns empty. It cannot bring
back what this dropped, and says so rather than pretending.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043_drop_looks"
down_revision = "0042_plan_garments"
branch_labels = None
depends_on = None

#: What `look_interactions.kind` could be. Here only so the downgrade can
#: recreate the type it dropped.
INTERACTION_KINDS = ("view", "search_piece", "ask_stylist", "save")


def upgrade() -> None:
    # ---------------------------------------------------------------- #
    # the columns that pointed at a look
    # ---------------------------------------------------------------- #
    # `batch_alter_table` throughout: SQLite cannot DROP COLUMN on a table
    # carrying constraints, so alembic rebuilds and copies instead.
    with op.batch_alter_table("posts") as batch:
        batch.drop_column("look_id")

    # The pin's unique constraint and check constraint both name `look_id`,
    # so they go before the column does. `post_id` becomes required: with
    # looks gone it is the only thing a pin can point at, and the check
    # constraint was what had been enforcing exactly one of the two.
    op.execute(sa.text("DELETE FROM moodboard_pins WHERE post_id IS NULL"))
    with op.batch_alter_table("moodboard_pins") as batch:
        batch.drop_constraint("uq_moodboard_pins_board_look", type_="unique")
        batch.drop_constraint("ck_moodboard_pins_one_subject", type_="check")
        batch.drop_column("look_id")
        batch.alter_column("post_id", existing_type=sa.Uuid(), nullable=False)

    with op.batch_alter_table("outfit_plans") as batch:
        batch.drop_column("look_id")

    with op.batch_alter_table("avatar_renders") as batch:
        batch.drop_column("look_id")

    # ---------------------------------------------------------------- #
    # the two tables about looks
    # ---------------------------------------------------------------- #
    op.drop_index("ix_saved_looks_user_saved_at", table_name="saved_looks")
    op.drop_table("saved_looks")

    op.drop_index("ix_look_interactions_occurred_at", table_name="look_interactions")
    op.drop_table("look_interactions")
    sa.Enum(name="look_interaction_kind").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Put the shapes back, empty.

    What `upgrade` dropped was the only copy. This restores somewhere for
    it to live, not the data itself.
    """
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

    op.create_table(
        "saved_looks",
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
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
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
        sa.UniqueConstraint("user_id", "look_id", name="uq_saved_looks_user_look"),
    )
    op.create_index(
        "ix_saved_looks_user_saved_at", "saved_looks", ["user_id", "saved_at"]
    )

    with op.batch_alter_table("avatar_renders") as batch:
        batch.add_column(sa.Column("look_id", sa.String(64), nullable=True))

    with op.batch_alter_table("outfit_plans") as batch:
        batch.add_column(sa.Column("look_id", sa.String(64), nullable=True))

    with op.batch_alter_table("moodboard_pins") as batch:
        batch.add_column(sa.Column("look_id", sa.String(64), nullable=True))
        batch.alter_column("post_id", existing_type=sa.Uuid(), nullable=True)
        batch.create_unique_constraint(
            "uq_moodboard_pins_board_look", ["moodboard_id", "look_id"]
        )
        batch.create_check_constraint(
            "ck_moodboard_pins_one_subject",
            "(look_id IS NULL) <> (post_id IS NULL)",
        )

    with op.batch_alter_table("posts") as batch:
        batch.add_column(sa.Column("look_id", sa.String(64), nullable=True))

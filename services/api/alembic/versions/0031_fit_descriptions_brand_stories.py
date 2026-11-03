"""Fit descriptions, brand stories, and composed prompts on a shot.

Three changes that go together.

``post_descriptions`` holds what the clothes in a posted fit are, read off
the photograph: the outfit sentence a try-on puts on somebody's avatar, a
caption naming the pieces, and the pieces themselves. Its own table rather
than columns on ``posts`` because it is derived data with a model and a
prompt version behind it, and because the author's caption must stay the
author's.

``brand_stories`` groups several frames generated from one product under one
brief. The frames are ``garment_shots`` rows, which is why that table gains
``story_id`` and ``position``.

``avatar_renders.source_post_id`` records that a try-on came from somebody
else's published fit rather than from a curated look, which is what makes
"Try it on" under a Discover photograph a real pipeline run with a traceable
source instead of an untitled picture.

``garment_shots.prompt`` is the composed prompt for a frame. A garment
studio shot leaves it null and runs its treatment's fixed wording; a brand
frame stores the prompt built from scene, cast, reference and brief, so the
run is reproducible and explainable after the fact.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_fit_descriptions_brand_stories"
down_revision = "0030_board_post_pins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_descriptions",
        sa.Column(
            "post_id",
            sa.Uuid(),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("outfit", sa.Text(), nullable=False),
        sa.Column("caption", sa.String(140), nullable=True),
        sa.Column("pieces", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(16), nullable=True),
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
    )

    op.create_table(
        "brand_stories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(120), nullable=True),
        sa.Column("brief", sa.String(600), nullable=True),
        sa.Column("cast", sa.JSON(), nullable=False),
        sa.Column(
            "reference_post_id",
            sa.Uuid(),
            sa.ForeignKey("posts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("style_note", sa.String(400), nullable=True),
        sa.Column(
            "state",
            sa.Enum("working", "ready", "partial", "failed", name="brand_story_state"),
            nullable=False,
            server_default="working",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_brand_stories_user_id_created_at",
        "brand_stories",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_brand_stories_deleted_at", "brand_stories", ["deleted_at"]
    )

    with op.batch_alter_table("avatar_renders") as batch:
        batch.add_column(sa.Column("source_post_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_avatar_renders_source_post",
            "posts",
            ["source_post_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("garment_shots") as batch:
        batch.add_column(sa.Column("prompt", sa.Text(), nullable=True))
        batch.add_column(sa.Column("story_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_garment_shots_story",
            "brand_stories",
            ["story_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index(
        "ix_garment_shots_story_position",
        "garment_shots",
        ["story_id", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_garment_shots_story_position", table_name="garment_shots")
    with op.batch_alter_table("garment_shots") as batch:
        batch.drop_constraint("fk_garment_shots_story", type_="foreignkey")
        batch.drop_column("position")
        batch.drop_column("story_id")
        batch.drop_column("prompt")
    with op.batch_alter_table("avatar_renders") as batch:
        batch.drop_constraint("fk_avatar_renders_source_post", type_="foreignkey")
        batch.drop_column("source_post_id")
    op.drop_index("ix_brand_stories_deleted_at", table_name="brand_stories")
    op.drop_index("ix_brand_stories_user_id_created_at", table_name="brand_stories")
    op.drop_table("brand_stories")
    op.drop_table("post_descriptions")
    sa.Enum(name="brand_story_state").drop(op.get_bind(), checkfirst=True)

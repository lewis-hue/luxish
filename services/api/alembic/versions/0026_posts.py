"""community: fits, behind a screen that fails closed

Revision ID: 0026_posts
Revises: 0025_shopping
Create Date: 2026-10-30

The first user-authored content a stranger can see, which is why it ships
after report, block and the screening job rather than before them. A post
is born `pending_review`; only the screen publishes it; screening being
unavailable holds it. `report_subject` gains a `post` value so the
controls that already exist cover the new surface from its first day.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_posts"
down_revision = "0025_shopping"
branch_labels = None
depends_on = None

STATES = ("pending_review", "published", "held", "removed")
REPORT_SUBJECTS = ("account", "look")
NEW_SUBJECT = "post"


def upgrade() -> None:
    bind = op.get_bind()
    state: sa.types.TypeEngine
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        state = postgresql.ENUM(*STATES, name="post_state", create_type=False)
        sa.Enum(*STATES, name="post_state").create(bind, checkfirst=True)
        op.execute(
            f"ALTER TYPE report_subject ADD VALUE IF NOT EXISTS '{NEW_SUBJECT}'"
        )
    else:
        state = sa.Enum(*STATES, name="post_state")
        # SQLite renders the enum as VARCHAR + CHECK; widening it rewrites
        # the column, the same move 0021 made for consents.
        with op.batch_alter_table("reports") as batch:
            batch.alter_column(
                "subject_kind",
                existing_type=sa.Enum(*REPORT_SUBJECTS, name="report_subject"),
                type_=sa.Enum(*REPORT_SUBJECTS, NEW_SUBJECT, name="report_subject"),
                existing_nullable=False,
            )

    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("caption", sa.String(300), nullable=True),
        sa.Column("occasion", sa.String(64), nullable=True),
        sa.Column("look_id", sa.String(64), nullable=True),
        sa.Column("state", state, nullable=False, server_default="pending_review"),
        sa.Column("screen_mode", sa.String(32), nullable=True),
        sa.Column("screen_note", sa.String(300), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_posts_user_id", "posts", ["user_id"])
    op.create_index("ix_posts_user_id_state", "posts", ["user_id", "state"])
    op.create_index("ix_posts_published_at", "posts", ["published_at"])
    op.create_index("ix_posts_deleted_at", "posts", ["deleted_at"])

    op.create_table(
        "post_media",
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "media_asset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "post_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "garment_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("garments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "product_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("shop_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_post_items_post_id", "post_items", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_post_items_post_id", table_name="post_items")
    op.drop_table("post_items")
    op.drop_table("post_media")
    op.drop_index("ix_posts_deleted_at", table_name="posts")
    op.drop_index("ix_posts_published_at", table_name="posts")
    op.drop_index("ix_posts_user_id_state", table_name="posts")
    op.drop_index("ix_posts_user_id", table_name="posts")
    op.drop_table("posts")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="post_state").drop(bind, checkfirst=True)
        # PostgreSQL cannot drop an enum value; rows carrying it go, the
        # value harmlessly stays, as 0021 records.
        op.execute(f"DELETE FROM reports WHERE subject_kind = '{NEW_SUBJECT}'")
        return

    op.execute(f"DELETE FROM reports WHERE subject_kind = '{NEW_SUBJECT}'")
    with op.batch_alter_table("reports") as batch:
        batch.alter_column(
            "subject_kind",
            existing_type=sa.Enum(*REPORT_SUBJECTS, NEW_SUBJECT, name="report_subject"),
            type_=sa.Enum(*REPORT_SUBJECTS, name="report_subject"),
            existing_nullable=False,
        )

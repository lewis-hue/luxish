"""avatar renders: the 27-second call moves off the request path

Revision ID: 0018_avatar_renders
Revises: 0017_moodboards
Create Date: 2026-10-29

Drawing an avatar measured at 27 seconds and a try-on at 15 to 21, and both
were being awaited inside a request handler. Every other paid model call in
this service already goes through a durable job for the reasons ADR-005 and
ADR-013 record; the avatar was the exception, and an oversight rather than a
decision.

The row is created before the work starts, which is the whole of the
durability: "this person asked for a picture" survives the worker, the broker
and the model. A render that fails is a row saying why, not a request that
timed out with nothing behind it.

``pieces`` holds the garments **as they were requested**. When the avatar is
dressed in a look they are already known exactly, so re-detecting them out of
the finished picture would pay a vision call to guess at something in hand.
That is what makes a render tappable without a second model call.

``worn``-style three-valued nullability appears here too: ``media_asset_id``
is null until there is a picture, and ``error`` is null unless the state is
``failed``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_avatar_renders"
down_revision = "0017_moodboards"
branch_labels = None
depends_on = None

RENDER_KINDS = ("base", "try_on")
RENDER_STATES = ("queued", "running", "ready", "failed")


def upgrade() -> None:
    # Created explicitly, then referenced with `create_type=False`. Without
    # that flag `create_table` emits its own CREATE TYPE for the same enum and
    # the second one fails, leaving the type behind and the table absent — a
    # half-applied revision that then refuses to re-run.
    bind = op.get_bind()
    kind: sa.types.TypeEngine
    state: sa.types.TypeEngine
    if bind.dialect.name == "postgresql":
        kind = postgresql.ENUM(*RENDER_KINDS, name="avatar_render_kind", create_type=False)
        state = postgresql.ENUM(
            *RENDER_STATES, name="avatar_render_state", create_type=False
        )
        sa.Enum(*RENDER_KINDS, name="avatar_render_kind").create(bind, checkfirst=True)
        sa.Enum(*RENDER_STATES, name="avatar_render_state").create(bind, checkfirst=True)
    else:
        kind = sa.Enum(*RENDER_KINDS, name="avatar_render_kind")
        state = sa.Enum(*RENDER_STATES, name="avatar_render_state")

    op.create_table(
        "avatar_renders",
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
        sa.Column("kind", kind, nullable=False),
        sa.Column("state", state, nullable=False, server_default="queued"),
        sa.Column(
            "job_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "media_asset_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("look_id", sa.String(64), nullable=True),
        sa.Column("outfit", sa.String(500), nullable=True),
        sa.Column(
            "pieces",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("error", sa.String(300), nullable=True),
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
        "ix_avatar_renders_user_created", "avatar_renders", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_avatar_renders_user_created", table_name="avatar_renders")
    op.drop_table("avatar_renders")
    bind = op.get_bind()
    sa.Enum(name="avatar_render_state").drop(bind, checkfirst=True)
    sa.Enum(name="avatar_render_kind").drop(bind, checkfirst=True)

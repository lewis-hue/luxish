"""stylist: conversations, bounded runs, and validated outfits

Revision ID: 0008_stylist
Revises: 0007_external
Create Date: 2026-10-27

Task 8. Three schema properties carry invariants the application would
otherwise have to remember:

* ``outfit_items`` has two CHECK constraints. One refuses an item that
  identifies neither a garment nor a product; the other refuses an item that
  claims to be ``owned`` without a garment id, or a product suggestion that
  claims to be owned. The renderer branches on ``owned`` to decide whether to
  show a buy path, so a row that lies about it is a user-visible defect.
* ``garment_id`` is ``ON DELETE SET NULL``, not cascade. A hard-deleted garment
  leaves a visible hole in a past outfit instead of silently shrinking it.
* ``stylist_runs.explanation_code`` exists so "no feasible outfit" is a
  recorded answer rather than an empty response. A run that produced nothing is
  queryable.

There is no coordinate column in this migration. ``place`` is a name.

Numbering: the plan reserved ``0005_stylist`` for this task, but 0006 and 0007
have already landed, so inserting a revision between 0004 and 0006 would mean
rewriting two deployed ``down_revision`` values. This revision therefore
follows ``0007_external`` and the chain stays linear with one head:
0001 → 0002 → 0003 → 0004 → 0006 → 0007 → 0008. 0005 is permanently unused.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_stylist"
down_revision: str | None = "0007_external"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)

MESSAGE_ROLES = ("system", "user", "assistant", "tool")
RUN_STATES = ("queued", "running", "completed", "failed", "cancelled")
ITEM_ROLES = ("top", "bottom", "dress", "outer", "shoes", "bag", "accessory")
FEEDBACK_KINDS = ("would_wear", "wore", "dislike")

ENUMS = {
    "conversation_message_role": MESSAGE_ROLES,
    "stylist_run_state": RUN_STATES,
    "outfit_item_role": ITEM_ROLES,
    "outfit_feedback_kind": FEEDBACK_KINDS,
}


def _enum(name: str) -> sa.types.TypeEngine:
    """Named enum: a native type on PostgreSQL, VARCHAR + CHECK on SQLite."""
    values = ENUMS[name]
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def _create_enums() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)


def _drop_enums() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name in ENUMS:
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)


def upgrade() -> None:
    _create_enums()

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("last_run_at", TS, nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversations_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_deleted_at", "conversations", ["deleted_at"])
    op.create_index(
        "ix_conversations_user_id_created_at", "conversations", ["user_id", "created_at"]
    )

    op.create_table(
        "stylist_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("state", _enum("stylist_run_state"), server_default="queued", nullable=False),
        sa.Column("progress", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("request_text", sa.String(length=2000), nullable=True),
        sa.Column("occasion", sa.String(length=64), nullable=True),
        # A place NAME. No coordinate column exists here or anywhere else.
        sa.Column("place", sa.String(length=160), nullable=True),
        sa.Column("styled_for", sa.Date(), nullable=True),
        sa.Column("excluded", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("required", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("swap_slot", _enum("outfit_item_role"), nullable=True),
        sa.Column("locked_items", JSONB, server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "forbidden_garment_ids", JSONB, server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("tool_calls_used", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("model_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tool_executions", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("ai_run_ids", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("explanation_code", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("cancel_requested_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_stylist_runs_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_stylist_runs_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["stylist_runs.id"],
            name="fk_stylist_runs_parent_run_id_stylist_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_stylist_runs_job_id_jobs", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stylist_runs"),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 1", name="ck_stylist_runs_progress_range"
        ),
        sa.CheckConstraint(
            "tool_calls_used >= 0", name="ck_stylist_runs_tool_calls_used_non_negative"
        ),
        sa.CheckConstraint(
            "model_attempts >= 0", name="ck_stylist_runs_model_attempts_non_negative"
        ),
    )
    op.create_index("ix_stylist_runs_conversation_id", "stylist_runs", ["conversation_id"])
    op.create_index("ix_stylist_runs_user_id", "stylist_runs", ["user_id"])
    op.create_index("ix_stylist_runs_parent_run_id", "stylist_runs", ["parent_run_id"])
    op.create_index("ix_stylist_runs_job_id", "stylist_runs", ["job_id"])
    op.create_index(
        "ix_stylist_runs_user_id_created_at", "stylist_runs", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_stylist_runs_state_created_at", "stylist_runs", ["state", "created_at"]
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("role", _enum("conversation_message_role"), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        # True for anything from outside the trust boundary. A column, not a
        # convention: a replay must not be able to lose the distinction.
        sa.Column("untrusted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("origin_url", sa.String(length=2048), nullable=True),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["stylist_runs.id"],
            name="fk_conversation_messages_run_id_stylist_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"]
    )
    op.create_index("ix_conversation_messages_run_id", "conversation_messages", ["run_id"])
    op.create_index(
        "ix_conversation_messages_conversation_id_position",
        "conversation_messages",
        ["conversation_id", "position"],
    )

    op.create_table(
        "outfits",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("rationale", sa.String(length=600), nullable=True),
        sa.Column("occasion", sa.String(length=64), nullable=True),
        sa.Column("place", sa.String(length=160), nullable=True),
        sa.Column("styled_for", sa.Date(), nullable=True),
        sa.Column("missing_slots", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("saved", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_outfits_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_outfits_conversation_id_conversations",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["stylist_runs.id"],
            name="fk_outfits_run_id_stylist_runs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outfits"),
    )
    op.create_index("ix_outfits_user_id", "outfits", ["user_id"])
    op.create_index("ix_outfits_conversation_id", "outfits", ["conversation_id"])
    op.create_index("ix_outfits_run_id", "outfits", ["run_id"])
    op.create_index("ix_outfits_deleted_at", "outfits", ["deleted_at"])
    op.create_index("ix_outfits_user_id_created_at", "outfits", ["user_id", "created_at"])

    op.create_table(
        "outfit_items",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("outfit_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("garment_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("product_ref", sa.String(length=300), nullable=True),
        sa.Column("role", _enum("outfit_item_role"), nullable=False),
        sa.Column("owned", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["outfit_id"],
            ["outfits.id"],
            name="fk_outfit_items_outfit_id_outfits",
            ondelete="CASCADE",
        ),
        # SET NULL: a hard-deleted garment leaves a visible hole in history
        # rather than silently shrinking a past outfit.
        sa.ForeignKeyConstraint(
            ["garment_id"],
            ["garments.id"],
            name="fk_outfit_items_garment_id_garments",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outfit_items"),
        sa.UniqueConstraint(
            "outfit_id", "garment_id", name="uq_outfit_items_outfit_id_garment_id"
        ),
        sa.CheckConstraint(
            "garment_id IS NOT NULL OR product_ref IS NOT NULL",
            name="ck_outfit_items_identifies_something",
        ),
        sa.CheckConstraint(
            "(owned AND garment_id IS NOT NULL) OR (NOT owned AND product_ref IS NOT NULL)",
            name="ck_outfit_items_owned_means_garment",
        ),
    )
    op.create_index("ix_outfit_items_outfit_id", "outfit_items", ["outfit_id"])
    op.create_index("ix_outfit_items_garment_id", "outfit_items", ["garment_id"])
    op.create_index(
        "ix_outfit_items_outfit_id_position", "outfit_items", ["outfit_id", "position"]
    )

    op.create_table(
        "outfit_feedback",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("outfit_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", _enum("outfit_feedback_kind"), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["outfit_id"],
            ["outfits.id"],
            name="fk_outfit_feedback_outfit_id_outfits",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_outfit_feedback_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outfit_feedback"),
        sa.UniqueConstraint(
            "outfit_id", "user_id", "kind", name="uq_outfit_feedback_outfit_id_user_id_kind"
        ),
    )
    op.create_index("ix_outfit_feedback_outfit_id", "outfit_feedback", ["outfit_id"])
    op.create_index("ix_outfit_feedback_user_id", "outfit_feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_outfit_feedback_user_id", table_name="outfit_feedback")
    op.drop_index("ix_outfit_feedback_outfit_id", table_name="outfit_feedback")
    op.drop_table("outfit_feedback")

    op.drop_index("ix_outfit_items_outfit_id_position", table_name="outfit_items")
    op.drop_index("ix_outfit_items_garment_id", table_name="outfit_items")
    op.drop_index("ix_outfit_items_outfit_id", table_name="outfit_items")
    op.drop_table("outfit_items")

    op.drop_index("ix_outfits_user_id_created_at", table_name="outfits")
    op.drop_index("ix_outfits_deleted_at", table_name="outfits")
    op.drop_index("ix_outfits_run_id", table_name="outfits")
    op.drop_index("ix_outfits_conversation_id", table_name="outfits")
    op.drop_index("ix_outfits_user_id", table_name="outfits")
    op.drop_table("outfits")

    op.drop_index(
        "ix_conversation_messages_conversation_id_position", table_name="conversation_messages"
    )
    op.drop_index("ix_conversation_messages_run_id", table_name="conversation_messages")
    op.drop_index(
        "ix_conversation_messages_conversation_id", table_name="conversation_messages"
    )
    op.drop_table("conversation_messages")

    op.drop_index("ix_stylist_runs_state_created_at", table_name="stylist_runs")
    op.drop_index("ix_stylist_runs_user_id_created_at", table_name="stylist_runs")
    op.drop_index("ix_stylist_runs_job_id", table_name="stylist_runs")
    op.drop_index("ix_stylist_runs_parent_run_id", table_name="stylist_runs")
    op.drop_index("ix_stylist_runs_user_id", table_name="stylist_runs")
    op.drop_index("ix_stylist_runs_conversation_id", table_name="stylist_runs")
    op.drop_table("stylist_runs")

    op.drop_index("ix_conversations_user_id_created_at", table_name="conversations")
    op.drop_index("ix_conversations_deleted_at", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")

    _drop_enums()

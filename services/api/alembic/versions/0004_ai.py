"""ai: run accounting, provider connections, and usage reservations

Revision ID: 0004_ai
Revises: 0003_jobs
Create Date: 2026-10-26

Task 7. Three tables, each carrying one invariant into the schema:

* ``ai_runs`` records every model call — prompt version, provider, model, token
  counts, integer cost, outcome. ``provider`` and ``model`` are plain strings,
  not enums: this is an append-only audit row and retiring a model must not make
  the history of its calls unreadable.
* ``provider_connections`` separates the *identity* link from the *inference*
  entitlement (``kind`` is part of the uniqueness key — ADR-008), and has no
  column that could hold a bearer token.
* ``usage_reservations.key`` is unique, so settling the same reservation twice
  is a no-op by schema rather than by caller diligence.

Numbered 0004 per the plan, so ``0007_external`` (Task 10, which landed first)
now follows this revision and the chain stays linear with one head.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_ai"
down_revision: str | None = "0003_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)

AI_RUN_OUTCOMES = (
    "pending",
    "succeeded",
    "failed",
    "refused",
    "rate_limited",
    "cancelled",
)
AI_PROVIDERS = ("meta", "chatgpt_plan")
CONNECTION_KINDS = ("identity", "inference")
CONNECTION_STATES = (
    "unavailable",
    "approval_pending",
    "disconnected",
    "identity_connected",
    "inference_authorized",
    "allowance_exhausted",
    "revoked",
    "error",
)
USAGE_RESERVATION_STATES = ("reserved", "reconciled", "released")

ENUMS = {
    "ai_run_outcome": AI_RUN_OUTCOMES,
    "ai_provider": AI_PROVIDERS,
    "provider_connection_kind": CONNECTION_KINDS,
    "provider_connection_state": CONNECTION_STATES,
    "usage_reservation_state": USAGE_RESERVATION_STATES,
}


def _enum(name: str) -> sa.types.TypeEngine:
    """The named enum: a native type on PostgreSQL, VARCHAR + CHECK on SQLite."""
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
        "ai_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        # SET NULL, not CASCADE: deleting a user must not delete the record of
        # what their runs cost.
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("team_id", sa.String(length=120), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=True),
        sa.Column("reservation_id", sa.String(length=120), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "outcome", _enum("ai_run_outcome"), server_default="pending", nullable=False
        ),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cached_input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "reasoning_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("images", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # Money is integer minor units (ADR-011). `cost_micro_minor` is the
        # exact figure; `cost_minor` is it rounded up to what a ledger can post.
        sa.Column("cost_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cost_micro_minor", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("response_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cost_micro_minor >= 0", name="ck_ai_runs_cost_micro_minor_non_negative"),
        sa.CheckConstraint("cost_minor >= 0", name="ck_ai_runs_cost_minor_non_negative"),
        sa.CheckConstraint("input_tokens >= 0", name="ck_ai_runs_input_tokens_non_negative"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_ai_runs_output_tokens_non_negative"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_ai_runs_job_id_jobs", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_ai_runs_user_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_runs"),
    )
    op.create_index("ix_ai_runs_job_id", "ai_runs", ["job_id"])
    op.create_index("ix_ai_runs_provider_model", "ai_runs", ["provider", "model"])
    op.create_index("ix_ai_runs_team_id_created_at", "ai_runs", ["team_id", "created_at"])
    op.create_index("ix_ai_runs_user_id_created_at", "ai_runs", ["user_id", "created_at"])

    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", _enum("ai_provider"), nullable=False),
        sa.Column("kind", _enum("provider_connection_kind"), nullable=False),
        sa.Column(
            "state",
            _enum("provider_connection_state"),
            server_default="unavailable",
            nullable=False,
        ),
        sa.Column("scopes", JSONB, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("plan_tier", sa.String(length=32), nullable=True),
        # A Secret Manager resource name. There is deliberately no
        # `access_token` or `refresh_token` column here.
        sa.Column("credential_ref", sa.String(length=512), nullable=True),
        sa.Column("external_subject", sa.String(length=255), nullable=True),
        sa.Column("terminal", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "refresh_required", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("last_error_code", sa.String(length=96), nullable=True),
        sa.Column("last_error_status", sa.Integer(), nullable=True),
        sa.Column("last_error_at", TS, nullable=True),
        sa.Column("unsupported_param", sa.String(length=255), nullable=True),
        sa.Column(
            "consecutive_transient_failures",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "retry_after_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("approval_requested_at", TS, nullable=True),
        sa.Column("connected_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "consecutive_transient_failures >= 0",
            name="ck_provider_connections_transient_failures_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_provider_connections_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_connections"),
        # Identity and inference are separate permissions, so `kind` is part of
        # the key rather than a flag on one row (ADR-008).
        sa.UniqueConstraint(
            "user_id", "provider", "kind", name="uq_provider_connections_user_id_provider_kind"
        ),
    )
    op.create_index("ix_provider_connections_user_id", "provider_connections", ["user_id"])

    op.create_table(
        "usage_reservations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        # Meta's rate limits are per team, so reservations are held per team.
        sa.Column("team_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column(
            "state",
            _enum("usage_reservation_state"),
            server_default="reserved",
            nullable=False,
        ),
        sa.Column(
            "estimated_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "estimated_micro_minor",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("actual_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_micro_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("reserved_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("settled_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "actual_tokens IS NULL OR actual_tokens >= 0",
            name="ck_usage_reservations_actual_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "estimated_tokens >= 0",
            name="ck_usage_reservations_estimated_tokens_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_usage_reservations_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usage_reservations"),
        # Settling the same reservation twice is a no-op by schema.
        sa.UniqueConstraint("key", name="uq_usage_reservations_key"),
    )
    op.create_index(
        "ix_usage_reservations_team_id_created_at",
        "usage_reservations",
        ["team_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_usage_reservations_team_id_created_at", table_name="usage_reservations"
    )
    op.drop_table("usage_reservations")
    op.drop_index("ix_provider_connections_user_id", table_name="provider_connections")
    op.drop_table("provider_connections")
    op.drop_index("ix_ai_runs_user_id_created_at", table_name="ai_runs")
    op.drop_index("ix_ai_runs_team_id_created_at", table_name="ai_runs")
    op.drop_index("ix_ai_runs_provider_model", table_name="ai_runs")
    op.drop_index("ix_ai_runs_job_id", table_name="ai_runs")
    op.drop_table("ai_runs")
    _drop_enums()

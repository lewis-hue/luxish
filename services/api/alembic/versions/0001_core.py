"""core: users, external identities, sessions, revocation, consent, preferences

Revision ID: 0001_core
Revises: None
Create Date: 2026-10-26

Task 4. Keycloak is the identity provider; this schema holds no bearer material
of its own. ``external_identities`` is keyed on ``(provider, subject)`` — never
on email — and ``revoked_tokens`` / ``sessions`` carry the denial state that a
JWT cannot express.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)

IDENTITY_PROVIDERS = ("keycloak", "apple", "google", "chatgpt")
CONSENT_KINDS = (
    "publication",
    "ai_processing",
    "location_precise",
    "location_coarse",
    "analytics",
)


def _enum(name: str, values: tuple[str, ...]) -> sa.types.TypeEngine:
    """Reference an existing named enum without re-emitting CREATE TYPE.

    On PostgreSQL the type is created once, up front; on SQLite each column
    gets its own VARCHAR + CHECK, which is what ``sa.Enum`` renders there.
    """
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def _create_enums() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    postgresql.ENUM(*IDENTITY_PROVIDERS, name="identity_provider").create(bind, checkfirst=True)
    postgresql.ENUM(*CONSENT_KINDS, name="consent_kind").create(bind, checkfirst=True)


def _drop_enum(name: str) -> None:
    """PostgreSQL keeps a named type after its tables are dropped; SQLite has none."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)


def upgrade() -> None:
    _create_enums()
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "email_verified", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])
    # One live account per address; a soft-deleted row must not burn the address.
    op.create_index(
        "uq_users_email_live",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", _enum("identity_provider", IDENTITY_PROVIDERS), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email_at_link", sa.String(length=320), nullable=True),
        sa.Column(
            "email_verified_at_link",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "linked_by_confirmation",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("last_seen_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_external_identities_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_external_identities"),
        sa.UniqueConstraint(
            "provider", "subject", name="uq_external_identities_provider_subject"
        ),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])

    op.create_table(
        "identity_link_challenges",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("provider", _enum("identity_provider", IDENTITY_PROVIDERS), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("claimed_email", sa.String(length=320), nullable=True),
        sa.Column(
            "claimed_email_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("consumed_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_identity_link_challenges_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identity_link_challenges"),
    )
    op.create_index(
        "ix_identity_link_challenges_provider_subject",
        "identity_link_challenges",
        ["provider", "subject"],
    )
    op.create_index(
        "ix_identity_link_challenges_user_id", "identity_link_challenges", ["user_id"]
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("keycloak_sid", sa.String(length=255), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("last_seen_at", TS, nullable=True),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("keycloak_sid", name="uq_sessions_keycloak_sid"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_revoked_at", "sessions", ["revoked_at"])

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("revoked_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_revoked_tokens_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("jti", name="pk_revoked_tokens"),
    )
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])

    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", _enum("consent_kind", CONSENT_KINDS), nullable=False),
        sa.Column("granted_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_consents_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_consents"),
        sa.UniqueConstraint("user_id", "kind", name="uq_consents_user_id_kind"),
    )
    op.create_index("ix_consents_user_id", "consents", ["user_id"])

    op.create_table(
        "preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_preferences_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_preferences"),
        sa.UniqueConstraint("user_id", "key", name="uq_preferences_user_id_key"),
    )
    op.create_index("ix_preferences_user_id", "preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_preferences_user_id", table_name="preferences")
    op.drop_table("preferences")
    op.drop_index("ix_consents_user_id", table_name="consents")
    op.drop_table("consents")
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    op.drop_index("ix_sessions_revoked_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(
        "ix_identity_link_challenges_user_id", table_name="identity_link_challenges"
    )
    op.drop_index(
        "ix_identity_link_challenges_provider_subject",
        table_name="identity_link_challenges",
    )
    op.drop_table("identity_link_challenges")
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_index("uq_users_email_live", table_name="users")
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_table("users")
    _drop_enum("consent_kind")
    _drop_enum("identity_provider")

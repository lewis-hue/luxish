"""consent: sharing what you keep with people who follow you

Revision ID: 0021_community_sharing
Revises: 0020_follows
Create Date: 2026-10-30

The community feed shipped showing, to anybody who followed you, which looks
you had saved. Following is unilateral — there is no request to accept — so
in effect a stranger could learn your private collection by tapping Follow.
Nothing in the app had ever told anyone that saving a look would be visible
to another person: the Saved screen reads as a personal shelf, and it is one.

That was a real disclosure and this revision is the fix. Appearing in anyone
else's feed now requires an explicit, withdrawable grant, which lands in the
same consents table as every other permission this product asks for rather
than in a bare boolean nobody audits.

**Default is off and must stay off.** The row simply does not exist until
somebody grants it, and `granted_at IS NULL` is read as "no" everywhere, so
every existing account is private from the moment this applies.

Adding a value to a named enum is the awkward part. PostgreSQL needs
``ALTER TYPE``; SQLite renders the enum as VARCHAR with a CHECK constraint,
which `batch_alter_table` rewrites by copying the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_community_sharing"
down_revision = "0020_follows"
branch_labels = None
depends_on = None

NEW_VALUE = "community_sharing"
EXISTING = (
    "publication",
    "ai_processing",
    "location_precise",
    "location_coarse",
    "analytics",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Outside a transaction block on older servers; 12+ allows it inline,
        # and `IF NOT EXISTS` makes a re-run harmless either way.
        op.execute(f"ALTER TYPE consent_kind ADD VALUE IF NOT EXISTS '{NEW_VALUE}'")
        return

    # SQLite: the enum is a CHECK constraint, so the column is rewritten with
    # the wider set of values.
    with op.batch_alter_table("consents") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*EXISTING, name="consent_kind"),
            type_=sa.Enum(*EXISTING, NEW_VALUE, name="consent_kind"),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL cannot drop a value from an enum. Rows carrying it are
        # removed so the type is at least consistent with the narrower set;
        # the type itself keeps the value, which is harmless and unreachable
        # once the application no longer offers it.
        op.execute(f"DELETE FROM consents WHERE kind = '{NEW_VALUE}'")
        return

    op.execute(f"DELETE FROM consents WHERE kind = '{NEW_VALUE}'")
    with op.batch_alter_table("consents") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*EXISTING, NEW_VALUE, name="consent_kind"),
            type_=sa.Enum(*EXISTING, name="consent_kind"),
            existing_nullable=False,
        )

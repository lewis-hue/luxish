"""A private account.

Public is the default and stays the default: everything this app does
with a fit assumes somebody published it on purpose. Private is the
switch for people who want the app without the audience - their
photographs and the two lists of who they are connected to stop
crossing to strangers, and the counts stay, because a count is not a
list and hiding it would only say "this person has something to hide".

Not a consent: `community_sharing` is a grant about a *shelf* of other
people's looks, and overloading it to mean "and also everything I
posted" would make one switch answer two different questions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_private_accounts"
down_revision = "0037_post_hides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(
            sa.Column(
                "private",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("private")

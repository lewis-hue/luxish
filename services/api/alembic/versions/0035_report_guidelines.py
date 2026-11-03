"""Comments can be reported, and a report can name the guideline.

Reports offered four generic reasons - impersonation, inappropriate,
spam, other - while the screen enforced a different set written as prose
inside a prompt, and nothing told anybody what either was. The
guidelines are now one list in `app.domain.guidelines`, and a report
points at the rule it claims was broken.

`reason` stays as it is. The four coarse values are what the existing
moderation queue sorts by, and widening an enum every time a guideline
is reworded would make the stored history unreadable. `guideline_id` is
the specific claim, stored as text for the same reason: a rule may be
renamed or retired without rewriting the reports that cited it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_report_guidelines"
down_revision = "0034_post_comments"
branch_labels = None
depends_on = None

SUBJECTS = ("account", "look", "post")
NEW_SUBJECT = "comment"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f"ALTER TYPE report_subject ADD VALUE IF NOT EXISTS '{NEW_SUBJECT}'"
        )
    else:
        with op.batch_alter_table("reports") as batch:
            batch.alter_column(
                "subject_kind",
                existing_type=sa.Enum(*SUBJECTS, name="report_subject"),
                type_=sa.Enum(*SUBJECTS, NEW_SUBJECT, name="report_subject"),
                existing_nullable=False,
            )

    with op.batch_alter_table("reports") as batch:
        # Text, not an enum: a guideline may be reworded or retired, and
        # a report that cited it is still a true record of what somebody
        # claimed at the time.
        batch.add_column(sa.Column("guideline_id", sa.String(40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reports") as batch:
        batch.drop_column("guideline_id")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL cannot drop an enum value; the rows carrying it go
        # so the type matches what the application will enforce again.
        op.execute(sa.text("DELETE FROM reports WHERE subject_kind = 'comment'"))
        return

    op.execute(sa.text("DELETE FROM reports WHERE subject_kind = 'comment'"))
    with op.batch_alter_table("reports") as batch:
        batch.alter_column(
            "subject_kind",
            existing_type=sa.Enum(*SUBJECTS, NEW_SUBJECT, name="report_subject"),
            type_=sa.Enum(*SUBJECTS, name="report_subject"),
            existing_nullable=False,
        )

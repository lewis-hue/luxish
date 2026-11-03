"""a shot keeps the direction it was asked for in

Revision ID: 0047_shot_brief
Revises: 0046_post_visibility
Create Date: 2026-11-01

One nullable column, beside the `prompt` that already exists, and the
two are deliberately not the same thing.

`prompt` is what was sent to the model - composed, long, and full of
wording nobody typed. `brief` is the sentence the person actually
wrote. Keeping only the first would mean their own words could not be
shown back to them, re-run, or edited without being dug back out of a
paragraph they never saw.

Null is the ordinary case and always will be: a treatment on its own
is a complete request, and a shot asked for without a direction runs
exactly the wording it ran before this revision.

Where the brief lands in the composed prompt is decided in
`app.workers.garment_studio.with_brief`, not here, and it matters: the
vendor's edit endpoint has no mask, so the clause protecting the source
garment is the only thing keeping the product the product - and an edit
follows its final instruction most closely. The brief goes after the
treatment and before that clause, never last.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_shot_brief"
down_revision = "0046_post_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "garment_shots",
        sa.Column("brief", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("garment_shots", "brief")

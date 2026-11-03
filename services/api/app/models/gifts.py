"""The credit ledger: append-only, integer, and honest about its store.

**Withdrawn, and kept anyway.** Gifting had a simulated
implementation and it was taken out of the app: it stood on a
member's page as a credit form nobody had asked for, below the
photographs people came to see. Nothing reads or writes this table
now. It stays because these rows are money, and a migration dropping
them for tidiness would be irreversible - bringing the feature back
is a router and a screen rather than a schema change.

ADR-011's money rules, applied to credits before any money exists: every
movement is a new row, a balance is a sum over rows and never a mutable
column, and amounts are integers. A retried request that wrote a second
row would double-spend, so the *pair* of rows a gift produces shares a
``transfer_id`` and the send path is the only writer.

**No message column, deliberately.** A gift that carries text is
user-generated content crossing between strangers, which needs the
moderation pipeline that does not exist yet. A gift that carries only a
number needs nothing but arithmetic.

``simulated_topup`` is the one way credits enter this build, and it says
so in the row forever. When Apple and Google IAP arrive their purchase
kinds join the enum; nothing already written changes meaning.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, named_enum, uuid_fk, uuid_pk

#: One account today. ``ai_allowance`` joins it when allowances stop being
#: derived; purchased and granted balances stay distinct account types.
CREDIT_ACCOUNTS: tuple[str, ...] = ("gift_credits",)

CREDIT_KINDS: tuple[str, ...] = ("simulated_topup", "gift_sent", "gift_received")

credit_account_enum = named_enum("credit_account", *CREDIT_ACCOUNTS)
credit_kind_enum = named_enum("credit_kind", *CREDIT_KINDS)


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        sa.Index("ix_credit_ledger_user_account", "user_id", "account"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    account: Mapped[str] = mapped_column(credit_account_enum, nullable=False)
    #: Signed integer credits. Negative is money out of this account.
    delta: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    kind: Mapped[str] = mapped_column(credit_kind_enum, nullable=False)
    #: The other person, for a gift. ``SET NULL`` so purging an account does
    #: not rewrite the arithmetic of everybody it ever gifted.
    counterparty_user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Shared by the two legs of one gift, so the pair is auditable as one
    #: event and a retry can be recognised.
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=sa.func.now()
    )

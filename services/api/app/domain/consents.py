"""Granting and withdrawing consent.

Consent is the gate on everything that sends a user's photographs or wardrobe
to a model, and until now it could be *read* but never *set*: the registry
refuses a provider without `ai_processing` consent, and nothing in the product
could grant it. A gate with no handle is a feature nobody can use, which is
how the stylist came to report that the styling service was unavailable when
it was working perfectly and correctly declining.

Three properties, each of which is the point rather than an implementation
detail:

* **Withdrawal is as easy as granting.** Same endpoint, same shape, one
  boolean. A consent that takes more effort to withdraw than to give is not
  freely given.
* **Nothing is implied.** A grant is recorded against a named kind, with when
  it happened and what asked for it. Agreeing to be styled is not agreeing to
  be published.
* **History survives.** Withdrawing stamps `revoked_at` on the row rather than
  deleting it, so "was this processed with consent at the time?" stays an
  answerable question.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.consent import CONSENT_KINDS, Consent


class UnknownConsentKind(ApiError):
    status_code = 422
    code = "unknown_consent_kind"
    default_message = "That is not a consent this service records."


async def set_consent(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    granted: bool,
    source: str = "app",
) -> Consent:
    """Grant or withdraw one consent. Idempotent in both directions.

    Granting twice is one grant and does not move the timestamp: the date
    somebody first agreed is the date they agreed, and refreshing it on every
    tap would quietly erase that.
    """
    if kind not in CONSENT_KINDS:
        raise UnknownConsentKind(f"Unknown consent kind: {kind!r}.")

    now = datetime.now(UTC)
    existing = await session.scalar(
        sa.select(Consent).where(Consent.user_id == user_id, Consent.kind == kind)
    )

    if existing is None:
        existing = Consent(
            user_id=user_id,
            kind=kind,
            granted_at=now if granted else None,
            revoked_at=None if granted else now,
            source=source,
        )
        session.add(existing)
    elif granted:
        # Re-granting after a withdrawal is a new grant; re-granting something
        # already held changes nothing.
        if not existing.is_granted:
            existing.granted_at = now
            existing.revoked_at = None
            existing.source = source
    else:
        existing.revoked_at = now

    await session.commit()
    await session.refresh(existing)
    return existing


async def list_consents(
    session: AsyncSession, *, user_id: uuid.UUID
) -> dict[str, Consent | None]:
    """Every kind this service records, and where this user stands on it.

    Returns an entry for every kind rather than only the rows that exist, so a
    client can render the full set without knowing the vocabulary, and so
    "never asked" is distinguishable from "declined".
    """
    rows = (
        await session.scalars(sa.select(Consent).where(Consent.user_id == user_id))
    ).all()
    by_kind = {row.kind: row for row in rows}
    return {kind: by_kind.get(kind) for kind in CONSENT_KINDS}


__all__ = ["CONSENT_KINDS", "UnknownConsentKind", "list_consents", "set_consent"]

"""The owned-garment revalidation chokepoint (ADR-010).

A garment id that came out of a model is an *assertion*. This module is the one
place that turns it into a fact, and it is one place on purpose: this is the
invariant whose failure is simultaneously invisible to the user and a privacy
breach, so it gets a single implementation with its own test rather than a check
at each call site that someone will eventually forget.

Four things are refused, and the refusal is deliberately indistinguishable
between the first two:

* an id belonging to another user,
* an id that does not exist,
* an archived garment,
* a garment marked ``laundry`` or ``unavailable``.

A model-invented or cross-user id fails the run with a structured error. It
never degrades into a plausible-looking outfit with one slot quietly missing —
partial success is the dangerous outcome here, because it reads as a styling
decision rather than a failure.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.garment import STYLEABLE_AVAILABILITY, Garment

#: An outfit is a handful of garments. A model returning hundreds of ids is
#: malfunctioning or being driven by injected text, and the right response is a
#: refusal before the query, not a 400-element ``IN`` clause. ASSUMED bound.
MAX_VALIDATED_IDS = 64

#: Reasons, most specific first. ``unknown`` deliberately covers both "not
#: yours" and "does not exist": distinguishing them would confirm that another
#: user's garment id is real.
VALIDATION_REASONS: tuple[str, ...] = (
    "malformed",
    "too_many",
    "unknown",
    "not_styleable",
)


class UnownedGarment(ApiError):
    """A garment id did not survive revalidation.

    One exception with a ``reason`` rather than four classes: a caller must not
    be able to handle "not mine" and forget "in the laundry". ``reason`` is for
    logs and for the run record; the rendered payload carries only the ids, so
    the response cannot be used to probe whether a stranger's id exists.
    """

    status_code = 409
    code = "unowned_garment"
    default_message = "A garment in that outfit is not available from your wardrobe."

    def __init__(
        self,
        reason: str,
        garment_ids: Iterable[object] = (),
        message: str | None = None,
    ) -> None:
        self.reason = reason
        self.garment_ids = [str(g) for g in garment_ids]
        super().__init__(message, detail={"garment_ids": self.garment_ids})


def _coerce(raw: object) -> uuid.UUID:
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        raise UnownedGarment("malformed", [raw]) from None


async def validate_owned_ids(
    session: AsyncSession,
    user_id: uuid.UUID,
    ids: Iterable[object],
) -> list[Garment]:
    """Return the garments for ``ids``, or raise :class:`UnownedGarment`.

    The query is scoped to ``user_id`` and to live rows, so an id belonging to
    another user, an id that never existed and a soft-deleted id all come back
    the same way: absent. Availability is then checked against
    ``STYLEABLE_AVAILABILITY``, which is how ``archived``, ``laundry`` and
    ``unavailable`` are rejected.

    Order is preserved and duplicates collapse to one garment, so a caller can
    zip the result against the slots it asked for.
    """
    requested = [_coerce(raw) for raw in ids]
    if not requested:
        return []

    # Dedupe while preserving first-seen order.
    ordered: list[uuid.UUID] = list(dict.fromkeys(requested))

    if len(ordered) > MAX_VALIDATED_IDS:
        raise UnownedGarment(
            "too_many",
            ordered[:MAX_VALIDATED_IDS],
            f"at most {MAX_VALIDATED_IDS} garment ids may be validated at once",
        )

    rows = (
        await session.scalars(
            sa.select(Garment).where(
                Garment.user_id == user_id,
                Garment.deleted_at.is_(None),
                Garment.id.in_(ordered),
            )
        )
    ).all()
    found = {row.id: row for row in rows}

    # Absent for *any* reason — someone else's, never existed, deleted.
    missing = [gid for gid in ordered if gid not in found]
    if missing:
        raise UnownedGarment("unknown", missing)

    not_styleable = [
        gid for gid in ordered if found[gid].availability not in STYLEABLE_AVAILABILITY
    ]
    if not_styleable:
        raise UnownedGarment("not_styleable", not_styleable)

    return [found[gid] for gid in ordered]


__all__ = [
    "MAX_VALIDATED_IDS",
    "VALIDATION_REASONS",
    "UnownedGarment",
    "validate_owned_ids",
]

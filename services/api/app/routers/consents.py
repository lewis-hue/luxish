"""Consent routes.

Thin, like the others. What is worth noticing is the shape rather than the
code: one endpoint sets a consent and the same endpoint withdraws it, with a
boolean. Making withdrawal harder than granting — a different endpoint, a
support email, a buried screen — is the pattern this deliberately avoids,
because a consent that is hard to withdraw was never freely given.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import AuthDep, SessionDep
from app.domain import consents
from app.schemas.consents import ConsentOut, ConsentSetIn, ConsentsResponse

router = APIRouter(prefix="/consents", tags=["consents"])


def _out(kind: str, record: object | None) -> ConsentOut:
    granted = bool(getattr(record, "is_granted", False))
    return ConsentOut(
        kind=kind,
        granted=granted,
        # Null means never asked, which a client should render differently
        # from declined: one is a question not yet put, the other an answer.
        granted_at=getattr(record, "granted_at", None) if granted else None,
        revoked_at=getattr(record, "revoked_at", None),
    )


@router.get("", response_model=ConsentsResponse)
async def read_consents(db: SessionDep, ctx: AuthDep) -> ConsentsResponse:
    """Every consent this service records, and where the caller stands."""
    records = await consents.list_consents(db, user_id=ctx.user_id)
    return ConsentsResponse(
        items=[_out(kind, record) for kind, record in records.items()]
    )


@router.put("/{kind}", response_model=ConsentOut)
async def set_consent(
    kind: str, payload: ConsentSetIn, db: SessionDep, ctx: AuthDep
) -> ConsentOut:
    """Grant or withdraw one consent.

    `PUT` rather than `POST`: this states what the consent *is*, so sending it
    twice is not two grants, and the client never has to know whether a row
    already existed.
    """
    record = await consents.set_consent(
        db,
        user_id=ctx.user_id,
        kind=kind,
        granted=payload.granted,
        source=payload.source or "app",
    )
    return _out(kind, record)

"""Wardrobe repository and rules.

Every query in here is scoped to one ``user_id``, and the scoping is applied by
``scoped_select`` rather than by callers — a router cannot forget it, because a
router never builds a query. A garment that exists but belongs to someone else
raises :class:`NotFound`, so the API answers 404 and never confirms the id.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError, NotFound
from app.models.garment import AVAILABILITY_VALUES, Garment
from app.models.media_asset import MediaAsset

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class InvalidCursor(ApiError):
    status_code = 400
    code = "invalid_cursor"
    default_message = "The pagination cursor could not be read."


@dataclass(slots=True)
class Page:
    items: Sequence[Garment]
    next_cursor: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def encode_cursor(garment: Garment) -> str:
    raw = json.dumps(
        {"created_at": garment.created_at.astimezone(UTC).isoformat(), "id": str(garment.id)}
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise InvalidCursor() from exc


class GarmentRepository:
    """Owner-scoped access to garments.

    Construct it with the authenticated user's id; there is no code path that
    reads a garment without one.
    """

    def __init__(self, session: AsyncSession, *, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id

    # -- scoping ----------------------------------------------------------- #
    def scoped_select(self) -> sa.Select[tuple[Garment]]:
        return sa.select(Garment).where(
            Garment.user_id == self.user_id, Garment.deleted_at.is_(None)
        )

    # -- reads -------------------------------------------------------------- #
    async def get(self, garment_id: uuid.UUID) -> Garment | None:
        return await self.session.scalar(self.scoped_select().where(Garment.id == garment_id))

    async def require(self, garment_id: uuid.UUID) -> Garment:
        garment = await self.get(garment_id)
        if garment is None:
            # Not yours and not existing are the same answer on purpose.
            raise NotFound("No such garment.")
        return garment

    async def list(
        self,
        *,
        cursor: str | None = None,
        category: str | None = None,
        availability: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page:
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        query = self.scoped_select()
        if category:
            query = query.where(Garment.category == category)
        if availability:
            if availability not in AVAILABILITY_VALUES:
                raise ApiError(
                    f"Unknown availability {availability!r}.",
                    status_code=422,
                    code="invalid_request",
                )
            query = query.where(Garment.availability == availability)
        if cursor:
            created_at, last_id = decode_cursor(cursor)
            query = query.where(
                sa.tuple_(Garment.created_at, Garment.id) < sa.tuple_(created_at, last_id)
            )
        query = query.order_by(Garment.created_at.desc(), Garment.id.desc()).limit(limit + 1)
        rows = list((await self.session.scalars(query)).all())
        next_cursor = encode_cursor(rows[limit - 1]) if len(rows) > limit else None
        return Page(items=rows[:limit], next_cursor=next_cursor)

    async def require_own_asset(self, asset_id: uuid.UUID) -> MediaAsset:
        asset = await self.session.scalar(
            sa.select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.user_id == self.user_id,
                MediaAsset.deleted_at.is_(None),
            )
        )
        if asset is None:
            raise NotFound("No such media asset.")
        return asset

    # -- writes ------------------------------------------------------------- #
    async def create(
        self,
        *,
        name: str | None = None,
        category: str | None = None,
        media_asset_id: uuid.UUID | None = None,
        confirmed_attributes: dict[str, Any] | None = None,
        availability: str = "available",
    ) -> Garment:
        if media_asset_id is not None:
            await self.require_own_asset(media_asset_id)
        garment = Garment(
            user_id=self.user_id,
            name=name,
            category=category,
            media_asset_id=media_asset_id,
            confirmed_attributes=_clean(confirmed_attributes or {}),
            inferred_attributes={},
            availability=availability,
        )
        self.session.add(garment)
        await self.session.commit()
        await self.session.refresh(garment)
        return garment

    async def apply_correction(
        self,
        garment_id: uuid.UUID,
        *,
        confirmed_attributes: dict[str, Any] | None = None,
        name: str | None = None,
        category: str | None = None,
        availability: str | None = None,
    ) -> Garment:
        """Record what the user says. Merges per key; an explicit null clears."""
        garment = await self.require(garment_id)
        if confirmed_attributes is not None:
            merged = dict(garment.confirmed_attributes or {})
            for key, value in confirmed_attributes.items():
                if value is None:
                    merged.pop(key, None)
                else:
                    merged[key] = value
            garment.confirmed_attributes = merged
        if name is not None:
            garment.name = name
        if category is not None:
            garment.category = category
        if availability is not None:
            if availability not in AVAILABILITY_VALUES:
                raise ApiError(
                    f"Unknown availability {availability!r}.",
                    status_code=422,
                    code="invalid_request",
                )
            garment.availability = availability
        await self.session.commit()
        await self.session.refresh(garment)
        return garment

    async def soft_delete(self, garment_id: uuid.UUID) -> None:
        garment = await self.require(garment_id)
        garment.deleted_at = _now()
        await self.session.commit()


def _clean(attributes: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in attributes.items() if v is not None}


async def apply_inference(
    session: AsyncSession,
    garment_id: uuid.UUID,
    attributes: dict[str, Any],
    confidence: float,
    *,
    inference_version: str | None = None,
) -> None:
    """Record a worker's inference.

    Deliberately unable to touch ``confirmed_attributes``: it writes only the
    inferred column, so a later, more confident result cannot overwrite a user
    correction. Not owner-scoped because the caller is a worker acting on a job
    whose asset ownership was already established — see Task 6's ``guard_write``.
    """
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be within [0, 1], got {confidence!r}")
    result = await session.execute(
        sa.update(Garment)
        .where(Garment.id == garment_id, Garment.deleted_at.is_(None))
        .values(
            inferred_attributes=dict(attributes),
            inference_confidence=confidence,
            inference_version=inference_version,
            inferred_at=_now(),
        )
    )
    if not result.rowcount:
        raise NotFound("No such garment.")
    await session.commit()

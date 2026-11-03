"""An avatar that looks like the person, built from their own photograph.

The avatar used to be drawn from a short vocabulary - a presentation, a
body type, a skin tone, an age band. That is enough to render *a* figure
and never enough to render *you*, which is the thing somebody is actually
trying to see when they ask how an outfit would look on them.

So: they upload a photograph of themselves and say anything they want
about it, and the picture is edited into a clean standing avatar. It
looks like them because it is them.

**Consent is its own question, asked before anything is read.** `likeness`
is a separate consent kind from `ai_processing`. Somebody can reasonably
want the stylist and not want their face sent to a model, and a grant for
one standing in for the other would make that impossible to say. Absent
means no, and the check happens before the photograph is opened.

**Nothing is inferred from the photograph.** This is the rule the whole
feature has to be built around, because it is the easy mistake: a picture
of a person is a tempting place to read a body type off. No attribute is
ever written from an image. The stated appearance stays what the person
stated, the note stays their own words, and the photograph is only ever
pixels handed to an edit.

**The photograph is theirs, re-validated.** An asset id in a request is a
claim. It is checked against the caller, and against the one media kind
this feature writes, so a garment photograph or somebody else's upload
cannot be routed through a face-generation call.

**It is removable, and removal is findable.** `source_asset_id` on the
render is what lets "delete the photo of my face" find the pictures drawn
from it. Removing the source tombstones the photograph and leaves the
renders - `SET NULL`, not `CASCADE` - because destroying pictures
somebody chose to keep is not what they asked for.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import avatar_renders
from app.models.avatar_render import AvatarRender
from app.models.consent import Consent
from app.models.media_asset import MediaAsset
from app.workers.avatar import AVATAR_SOURCE_MEDIA_KIND, MAX_LIKENESS_NOTE

#: Routed to the AI queue by the `avatar.` prefix, like the other two.
LIKENESS_JOB_KIND = "avatar.from_photo"

#: The consent this feature waits on.
LIKENESS_CONSENT = "likeness"


class NeedsLikenessConsent(Exception):
    """A face has not been agreed to, so nothing is read."""


class NoSuchPhotograph(Exception):
    """Not this caller's, not the right kind, or not readable."""


async def has_consent(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """Whether this person agreed to their likeness being generated.

    Absent means no. A consent row that was withdrawn means no. There is
    no default-on reading of this.
    """
    # Both halves, which is what `Consent.is_granted` means. Checking
    # only `granted_at` was a real defect and the worst possible one
    # here: a withdrawn consent left the grant timestamp in place, so a
    # face that somebody had explicitly taken back still went to the
    # model. A revocation has to be able to say no.
    found = await db.scalar(
        sa.select(Consent).where(
            Consent.user_id == user_id,
            Consent.kind == LIKENESS_CONSENT,
        )
    )
    return found is not None and found.is_granted


async def owned_photograph(
    db: AsyncSession, *, user_id: uuid.UUID, asset_id: uuid.UUID
) -> MediaAsset:
    """The uploaded photograph, if it is this caller's and the right kind.

    The kind check is not a formality. Without it, any asset id this
    person owns - a garment photograph, a studio shot - could be routed
    through a call whose prompt is "redraw this person", which is not
    what either of those is for.
    """
    asset = await db.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.user_id == user_id,
            MediaAsset.kind == AVATAR_SOURCE_MEDIA_KIND,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status.in_(("uploaded", "ready")),
        )
    )
    if asset is None or not asset.storage_key:
        raise NoSuchPhotograph()
    return asset


async def request(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    asset_id: uuid.UUID,
    note: str | None = None,
) -> AvatarRender:
    """Ask for an avatar drawn from this photograph. Returns at once.

    Consent first, ownership second, and only then a row and a job. The
    order matters: both refusals must happen before anything about the
    photograph is read, and before a billed call is queued against it.
    """
    if not await has_consent(db, user_id=user_id):
        raise NeedsLikenessConsent()

    asset = await owned_photograph(db, user_id=user_id, asset_id=asset_id)

    return await avatar_renders.request(
        db,
        user_id=user_id,
        kind="from_photo",
        source_asset_id=asset.id,
        note=(note or "").strip()[:MAX_LIKENESS_NOTE] or None,
    )


async def draw(
    db: AsyncSession,
    *,
    render: AvatarRender,
    renderer: object,
    store: object,
) -> MediaAsset:
    """Run the edit and keep the result. The worker's half.

    The source is re-read rather than trusted from the request: somebody
    may have deleted the photograph between asking and the job running,
    and a feature about a person's face should notice that rather than
    work from a stale handle.
    """
    from app.domain.avatar import store_avatar

    if render.source_asset_id is None:
        raise NoSuchPhotograph()

    source = await db.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == render.source_asset_id,
            MediaAsset.user_id == render.user_id,
            MediaAsset.kind == AVATAR_SOURCE_MEDIA_KIND,
            MediaAsset.deleted_at.is_(None),
            MediaAsset.status.in_(("uploaded", "ready")),
        )
    )
    if source is None or not source.storage_key:
        raise NoSuchPhotograph()

    # Withdrawn between the request and the run. A consent is a live
    # answer, not a token collected once, so it is checked again here -
    # this is the last moment before the face goes to the model.
    if not await has_consent(db, user_id=render.user_id):
        raise NeedsLikenessConsent()

    data = await store.read(source)  # type: ignore[attr-defined]
    drawn = await renderer.from_photo(  # type: ignore[attr-defined]
        photo=data,
        note=render.note,
        content_type=source.content_type or "image/jpeg",
        user_id=render.user_id,
    )
    return await store_avatar(
        db,
        user_id=render.user_id,
        data=drawn.data,
        content_type=drawn.content_type,
        store=store,
    )


async def photographs(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[MediaAsset]:
    """Every photograph of themselves this person has uploaded.

    Listed so it can be removed. A feature that takes a picture of
    somebody's face and offers no way to find it again is not one they
    can withdraw from in practice.
    """
    rows = await db.scalars(
        sa.select(MediaAsset)
        .where(
            MediaAsset.user_id == user_id,
            MediaAsset.kind == AVATAR_SOURCE_MEDIA_KIND,
            MediaAsset.deleted_at.is_(None),
        )
        .order_by(MediaAsset.created_at.desc())
    )
    return list(rows)


async def forget(
    db: AsyncSession, *, user_id: uuid.UUID, asset_id: uuid.UUID
) -> bool:
    """Remove an uploaded photograph of the person.

    The renders drawn from it are deliberately kept: the foreign key is
    `SET NULL`, and somebody deleting the source photograph is asking for
    the photograph to go, not for the avatar they liked to be destroyed.
    Deleting those is a separate action on the renders themselves.
    """
    asset = await db.scalar(
        sa.select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.user_id == user_id,
            MediaAsset.kind == AVATAR_SOURCE_MEDIA_KIND,
            MediaAsset.deleted_at.is_(None),
        )
    )
    if asset is None:
        return False
    asset.deleted_at = sa.func.now()
    await db.commit()
    return True


__all__ = [
    "LIKENESS_CONSENT",
    "LIKENESS_JOB_KIND",
    "NeedsLikenessConsent",
    "NoSuchPhotograph",
    "draw",
    "forget",
    "has_consent",
    "owned_photograph",
    "photographs",
    "request",
]

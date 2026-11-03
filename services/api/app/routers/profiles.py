"""Public identity: the handle, bio and links other people see.

Two readers, two shapes. `/me` is what the owner sees — including a bio
that is still in review and the note saying why one was held. The
`/{handle}` and `/{user_id}` views are what a stranger sees, which is
the approved bio and nothing about its state.
"""

from __future__ import annotations


from fastapi import APIRouter, status

from app.deps import AuthDep, SessionDep
from app.domain import profiles as domain
from app.domain.moderation import hidden_either_way
from app.errors import ApiError
from app.models.user import User
from app.models.profile import REACTION_EMOJI, SOCIAL_PLATFORMS
from app.schemas.profiles import (
    LinkOut,
    MyProfileOut,
    ProfileIn,
    PublicProfileOut,
    ReactionKindOut,
    ReactionsCatalogueOut,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _links(stored: dict) -> list[LinkOut]:
    out = []
    for platform, handle in (stored or {}).items():
        address = domain.address_for(platform, handle)
        if address:
            out.append(LinkOut(platform=platform, handle=handle, url=address))
    return out


@router.get("/reactions", response_model=ReactionsCatalogueOut)
async def reactions() -> ReactionsCatalogueOut:
    """The reaction set. Fixed, and the app renders exactly these."""
    return ReactionsCatalogueOut(
        items=[
            ReactionKindOut(kind=kind, emoji=emoji)
            for kind, emoji in REACTION_EMOJI.items()
        ]
    )


@router.get("/me", response_model=MyProfileOut)
async def mine(db: SessionDep, ctx: AuthDep) -> MyProfileOut:
    """Your own profile, including anything still in review."""
    profile = await domain.ensure(db, user_id=ctx.user_id)
    return MyProfileOut(
        user_id=ctx.user_id,
        handle=profile.handle,
        bio=profile.bio,
        bio_state=profile.bio_state,  # type: ignore[arg-type]
        bio_note=profile.bio_note,
        links=_links(profile.links),
        platforms=sorted(SOCIAL_PLATFORMS),
        banner_asset_id=profile.banner_asset_id,
        banner_state=profile.banner_state,  # type: ignore[arg-type]
        banner_note=profile.banner_note,
        private=profile.private,
    )


@router.patch("/me", response_model=MyProfileOut)
async def update(payload: ProfileIn, db: SessionDep, ctx: AuthDep) -> MyProfileOut:
    """Change the handle, the bio, or the links. Only what is sent."""
    try:
        if payload.handle is not None:
            await domain.set_handle(db, user_id=ctx.user_id, handle=payload.handle)
        if payload.private is not None:
            await domain.set_private(
                db, user_id=ctx.user_id, private=payload.private
            )
        if payload.links is not None:
            await domain.set_links(db, user_id=ctx.user_id, links=payload.links)
        if "bio" in payload.model_fields_set:
            await domain.set_bio(db, user_id=ctx.user_id, bio=payload.bio)
        if "banner_asset_id" in payload.model_fields_set:
            await domain.set_banner(
                db, user_id=ctx.user_id, asset_id=payload.banner_asset_id
            )
    except domain.BadHandle as refusal:
        raise ApiError(str(refusal), status_code=422, code="bad_handle") from None
    except domain.HandleTaken:
        raise ApiError(
            "That handle is taken.", status_code=409, code="handle_taken"
        ) from None
    except domain.BadLink as refusal:
        raise ApiError(str(refusal), status_code=422, code="bad_link") from None
    except domain.BadBanner:
        # The same answer for "not yours" and "not a banner": a
        # different one would confirm somebody else's asset id exists.
        raise ApiError(
            "No such picture.", status_code=404, code="not_found"
        ) from None
    return await mine(db, ctx)


@router.get("/{handle}", response_model=PublicProfileOut)
async def public(handle: str, db: SessionDep, ctx: AuthDep) -> PublicProfileOut:
    """Somebody else's profile, by handle. Only the approved bio crosses.

    **Blocks apply here, in both directions.** This endpoint shipped
    without that check while every other surface had it, which left a
    blocked person's handle, bio and links readable by anybody who knew
    the name — and left the blocker just as visible to them. A profile
    is the one surface that is *about* a person rather than about
    clothes, so it is the last place that rule should be missing.

    A deleted account is gone for the same reason, and all three
    refusals are the same 404: "blocked", "deleted" and "never existed"
    must be indistinguishable, or the refusal confirms what it denies.
    """
    profile = await domain.by_handle(db, handle=handle)
    missing = profile is None
    if not missing:
        hidden = await hidden_either_way(db, user_id=ctx.user_id)
        owner = await db.get(User, profile.user_id)
        missing = (
            profile.user_id in hidden
            or owner is None
            or owner.deleted_at is not None
        )
    if missing or profile is None:
        raise ApiError(
            "No such profile.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    return PublicProfileOut(
        user_id=profile.user_id,
        handle=profile.handle,
        bio=domain.public_bio(profile),
        links=_links(profile.links),
        banner_asset_id=domain.public_banner(profile),
    )

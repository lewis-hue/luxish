"""Auth routes.

Thin by design (ADR-003): no business rule lives here. Keycloak owns sign-in,
so there is no password, code, or social endpoint in this service — only
verification, session bookkeeping, and revocation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status

from app.deps import AuthDep, SessionDep, SettingsDep, VerifierDep
from app.domain import auth as auth_domain
from app.domain import profile_identity
from app.errors import ApiError, Unauthenticated
from app.schemas.auth import (
    IdentityLinkConfirmRequest,
    IdentityLinkConfirmResponse,
    MeResponse,
    SessionResponse,
    UpdateMeRequest,
)
from app.security.keycloak import LogoutTokenIncomplete, TokenRejected

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/session", response_model=SessionResponse)
async def create_session(ctx: AuthDep) -> SessionResponse:
    """Exchange a verified Keycloak token for local session state.

    Idempotent: presenting a token for an already-provisioned ``sub`` returns
    the same user. The response carries no credential — the client already holds
    the only one that exists.
    """
    return SessionResponse(
        user_id=ctx.user.id,
        email=ctx.user.email,
        email_verified=ctx.user.email_verified,
        session_id=ctx.session.id if ctx.session else None,
        expires_at=ctx.session.expires_at if ctx.session else ctx.claims.expires_at,
    )


@router.get("/me", response_model=MeResponse)
async def me(ctx: AuthDep) -> MeResponse:
    return MeResponse(
        user_id=ctx.user.id,
        email=ctx.user.email,
        email_verified=ctx.user.email_verified,
        display_name=ctx.user.display_name,
        profile_photo_asset_id=ctx.user.profile_photo_media_asset_id,
    )


@router.patch("/me", response_model=MeResponse)
async def update_me(
    payload: UpdateMeRequest, ctx: AuthDep, db: SessionDep
) -> MeResponse:
    """Change the name and photograph somebody shows in the app.

    Only the fields actually present in the body are touched, so a client
    editing the name cannot blank the photograph by omitting it. The
    photograph is given as a media asset id and re-validated against this
    user's own media before it is stored — an id from a client is a claim.
    """
    try:
        user = await profile_identity.set_profile(
            db,
            user_id=ctx.user_id,
            display_name=payload.display_name,
            photo_asset_id=payload.profile_photo_asset_id,
            fields=payload.fields_sent(),
        )
    except profile_identity.ProfilePhotoNotFound:
        # `ApiError`, not `HTTPException`: this app renders its own envelope
        # and a raw HTTPException's detail is flattened to the generic
        # `not_found`, losing the only part a client could act on.
        raise ApiError(
            "That picture is not one of yours.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="media_not_found",
        ) from None

    return MeResponse(
        user_id=user.id,
        email=user.email,
        email_verified=user.email_verified,
        display_name=user.display_name,
        profile_photo_asset_id=user.profile_photo_media_asset_id,
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(ctx: AuthDep, db: SessionDep) -> Response:
    await auth_domain.revoke_current_session(db, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/identity/link", response_model=IdentityLinkConfirmResponse)
async def confirm_identity_link(
    payload: IdentityLinkConfirmRequest, ctx: AuthDep, db: SessionDep
) -> IdentityLinkConfirmResponse:
    identity = await auth_domain.confirm_identity_link(
        db, actor=ctx, challenge_id=payload.link_challenge_id
    )
    return IdentityLinkConfirmResponse(
        identity_id=identity.id, provider=identity.provider, user_id=identity.user_id
    )


@router.post("/backchannel-logout", status_code=status.HTTP_204_NO_CONTENT)
async def backchannel_logout(
    request: Request, db: SessionDep, verifier: VerifierDep, settings: SettingsDep
) -> Response:
    """OIDC back-channel logout.

    Unauthenticated by design — the logout token *is* the authentication, and it
    is verified exactly like an access token plus the required logout event.
    """
    raw = (await request.body()).decode("utf-8", errors="replace").strip()
    if not raw:
        raise Unauthenticated("A logout token is required.")
    if raw.startswith("logout_token="):  # form-encoded variant
        from urllib.parse import parse_qs

        raw = (parse_qs(raw).get("logout_token") or [""])[0].strip()
    try:
        claims = await verifier.verify_logout_token(raw)
    except LogoutTokenIncomplete as exc:
        # Authentic sender, unusable message: this is a bad request, not a
        # failed authentication.
        raise ApiError(
            "The logout token names neither a session nor a subject.",
            status_code=400,
            code="invalid_logout_token",
        ) from exc
    except TokenRejected as exc:
        logger.info("logout token rejected", extra={"reason": exc.reason})
        raise Unauthenticated("The logout token was not accepted.") from exc

    revoked = await auth_domain.apply_backchannel_logout(db, claims)
    logger.info("backchannel logout applied", extra={"sessions_revoked": revoked})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


account_router = APIRouter(tags=["auth"])


@account_router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(ctx: AuthDep, db: SessionDep) -> Response:
    """Delete the account. Idempotent, and revokes every session."""
    await auth_domain.delete_account(db, user_id=ctx.user_id)
    if ctx.claims.jti:
        await auth_domain.record_revoked_token(
            db,
            jti=ctx.claims.jti,
            user_id=ctx.user_id,
            expires_at=ctx.claims.expires_at,
            reason="account_deleted",
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

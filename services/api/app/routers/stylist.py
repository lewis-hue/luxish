"""Stylist routes.

Thin, like the other routers: no query and no model call is built here. The
only thing this module decides is HTTP.

``POST /v1/stylist/runs`` answers **202**, never 200 with an outfit. Model work
is queued and never awaited in a request handler (ADR-013) — Cloud Run's
request timeout makes the alternative a liability, and a styling turn that
makes several provider calls would sit well inside it. The client polls
``GET /v1/stylist/runs/{id}``, which reports ``state``, ``progress``, the
outfit when there is one, and an ``explanation_code`` when there is not.

``POST /v1/stylist/ask`` is the one exception, and it is a deliberate
one. It answers a question in words and streams them back as they are
written. The rule it bends is "no model call in a handler"; the reason
the rule exists is Cloud Run's request timeout against image work that
takes 15 to 30 seconds, and this is a short text completion measured at
six. The expensive half - drawing the avatar - is still queued from
inside it. Cheap and interactive in the request; expensive and durable
on a worker.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse

from app.deps import AuthDep, SessionDep
from app.domain import stylist
from app.schemas.stylist import (
    AskCreate,
    AssistantOut,
    CapabilityOut,
    FeedbackCreate,
    FeedbackOut,
    OutfitItemOut,
    OutfitOut,
    OutfitPageOut,
    RunAccepted,
    RunCreate,
    RunOut,
    SwapRequest,
    ToolExecutionOut,
)

router = APIRouter(prefix="/stylist", tags=["stylist"])


def _outfit_out(view: stylist.OutfitView) -> OutfitOut:
    return OutfitOut(
        id=view.id,
        items=[
            OutfitItemOut(
                role=item.role,  # type: ignore[arg-type]
                owned=item.owned,
                garment_id=item.garment_id,
                product_ref=item.product_ref,
                name=item.name,
                category=item.category,
                attributes=item.attributes,
            )
            for item in view.items
        ],
        rationale=view.rationale,
        occasion=view.occasion,
        place=view.place,
        styled_for=view.styled_for,
        missing_slots=list(view.missing_slots),
        created_at=view.created_at,
    )


def _run_out(view: stylist.StylistRunView) -> RunOut:
    return RunOut(
        id=view.id,
        conversation_id=view.conversation_id,
        state=view.state,  # type: ignore[arg-type]
        progress=view.progress,
        outfit=_outfit_out(view.outfit) if view.outfit is not None else None,
        explanation=view.explanation,
        explanation_code=view.explanation_code,
        prompt_version=view.prompt_version,
        provider=view.provider,
        model=view.model,
        tool_calls_used=view.tool_calls_used,
        tool_executions=[
            ToolExecutionOut(name=e.name, ok=e.ok, error_code=e.error_code)
            for e in view.tool_executions
        ],
        error_code=view.error_code,
        swap_slot=view.swap_slot,  # type: ignore[arg-type]
        parent_run_id=view.parent_run_id,
        excluded=list(view.excluded),
        required=list(view.required),
    )


@router.get("/can", response_model=AssistantOut)
async def capabilities() -> AssistantOut:
    """What you can ask for, and what is not available.

    Static and the same for everybody. A client renders these as examples
    of what to say, never as buttons: the point of routing by sentence is
    that the screen stays one input box.
    """
    from app.domain import assistant
    from app.workers.brand_studio import VIDEO_REASON, VIDEO_STATUS

    return AssistantOut(
        items=[
            CapabilityOut(
                intent=item.intent,
                label=item.label,
                description=item.description,
                needs=list(item.needs),
            )
            for item in assistant.what_it_can_do()
        ],
        video=VIDEO_STATUS,
        video_reason=VIDEO_REASON,
    )


@router.post("/runs", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_run(payload: RunCreate, db: SessionDep, ctx: AuthDep) -> RunAccepted:
    """Queue a styling run. Returns 202 with an id to poll.

    ``place`` is a name the user typed. No device location is involved, so a
    user who declined location permission reaches exactly this code path.
    """
    run = await stylist.start_run(
        db,
        user_id=ctx.user_id,
        text=payload.text,
        occasion=payload.occasion,
        place=payload.place_name,
        date=payload.date,
        garment_id=payload.garment_id,
        asset_id=payload.media_asset_id,
        post_id=payload.post_id,
        attachments=[
            stylist.Attachment(
                source=item.source, text=item.text, origin_url=item.origin_url
            )
            for item in payload.attachments
        ],
        conversation_id=payload.conversation_id,
    )
    return RunAccepted(
        run_id=run.id, conversation_id=run.conversation_id, state=run.state  # type: ignore[arg-type]
    )


@router.get("/runs/{run_id}", response_model=RunOut)
async def read_run(run_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> RunOut:
    """Poll a run. A completed run with ``outfit: null`` is a real answer."""
    return _run_out(await stylist.load_run_view(db, user_id=ctx.user_id, run_id=run_id))


@router.post(
    "/runs/{run_id}/swap", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def swap_slot(
    run_id: uuid.UUID, payload: SwapRequest, db: SessionDep, ctx: AuthDep
) -> RunAccepted:
    """Queue a revision of one slot, keeping the rest of the outfit locked."""
    run = await stylist.swap_item(
        db, user_id=ctx.user_id, run_id=run_id, slot=payload.slot
    )
    return RunAccepted(
        run_id=run.id, conversation_id=run.conversation_id, state=run.state  # type: ignore[arg-type]
    )


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> RunOut:
    """Ask a running loop to stop. It notices between steps."""
    await stylist.request_cancellation(db, user_id=ctx.user_id, run_id=run_id)
    return _run_out(await stylist.load_run_view(db, user_id=ctx.user_id, run_id=run_id))


@router.post(
    "/outfits/{outfit_id}/feedback",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    outfit_id: uuid.UUID, payload: FeedbackCreate, db: SessionDep, ctx: AuthDep
) -> FeedbackOut:
    feedback = await stylist.record_feedback(
        db,
        user_id=ctx.user_id,
        outfit_id=outfit_id,
        kind=payload.kind,
        note=payload.note,
    )
    return FeedbackOut.model_validate(feedback)


@router.get("/outfits", response_model=OutfitPageOut)
async def list_outfits(
    db: SessionDep,
    ctx: AuthDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> OutfitPageOut:
    page = await stylist.list_outfits(db, user_id=ctx.user_id, cursor=cursor, limit=limit)
    return OutfitPageOut(
        items=[_outfit_out(view) for view in page.items], next_cursor=page.next_cursor
    )

@router.post("/ask")
async def ask(payload: AskCreate, db: SessionDep, ctx: AuthDep) -> StreamingResponse:
    """Answer a question about this person's wardrobe, streaming.

    Server-sent events, one JSON object per line:

        {"event": "token",    "text": "Yes, you "}
        {"event": "verdict",  "has_match": true, "using": [...]}
        {"event": "shopping", "items": [...]}
        {"event": "render",   "render_id": "..."}
        {"event": "done"}

    **SSE rather than a websocket** because this is one short
    one-directional burst per question. A socket would be a
    connection to keep alive, authenticate separately and reconnect,
    for a stream that lives six seconds.
    """
    import json as _json

    from app.domain import stylist_ask
    from app.providers.base import AIRunRecorder
    from app.providers.meta import MetaProvider

    provider = MetaProvider(recorder=AIRunRecorder(db))

    async def events():
        try:
            async for name, body in stylist_ask.stream_answer(
                db,
                user_id=ctx.user_id,
                question=payload.question,
                post_id=payload.post_id,
                history=[(t.who, t.text) for t in payload.history],
                provider=provider,
            ):
                if name == "token":
                    line = {"event": "token", "text": body}
                elif name == "verdict":
                    line = {
                        "event": "verdict",
                        "has_match": body.has_match,
                        "using": [str(g) for g in body.using],
                        "missing": list(body.missing),
                    }
                elif name == "shopping":
                    line = {
                        "event": "shopping",
                        "items": [_offer(m) for m in body],
                    }
                elif name == "render":
                    line = {"event": "render", "render_id": str(body)}
                else:
                    line = {"event": "done"}
                yield f"data: {_json.dumps(line)}\n\n"
            await db.commit()
        except Exception:  # noqa: BLE001
            # The stream has already started, so there is no status
            # code left to change. Saying so in-band is the only way
            # the client learns anything.
            yield 'data: {"event": "error"}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Proxies that buffer would hold the whole reply and
            # undo the streaming entirely.
            "X-Accel-Buffering": "no",
        },
    )


def _offer(match) -> dict:
    """One shoppable thing, as the client renders it."""
    product = getattr(match, "product", None)
    return {
        "product_id": str(getattr(match, "product_id", "") or ""),
        "title": getattr(product, "title", None) or getattr(match, "title", None),
        "retailer": getattr(product, "retailer", None),
        "url": getattr(product, "url", None),
        "match_label": getattr(match, "match_label", None),
    }

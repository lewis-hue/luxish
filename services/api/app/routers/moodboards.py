"""Moodboard routes.

A board is made, named, pinned to and arranged. Pinning is `PUT` on the
thing being pinned rather than `POST` to a collection, because pinning the
same thing twice is pinning it once and the client should not have to know
whether it already had.

Looks and published fits get separate paths rather than one path taking
either kind of id. A single segment would have to carry a type prefix, which
puts a parser in the URL and makes a 404 ambiguous between "no such board"
and "that is not a well formed id".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.deps import AuthDep, SessionDep
from app.domain import moodboards as domain
from app.schemas.moodboards import (
    BoardFitOut,
    BoardIn,
    BoardOut,
    BoardsResponse,
    PinsResponse,
    ReorderIn,
)

router = APIRouter(prefix="/moodboards", tags=["moodboards"])


async def _out(db: SessionDep, board: object) -> BoardOut:
    from app.domain.community import _first_pictures

    pinned = await domain.pins(db, board_id=getattr(board, "id"))
    posts = [r.post_id for r in pinned]
    # One query for the whole board, the same way a member's grid
    # resolves its covers.
    covers = await _first_pictures(db, posts)
    return BoardOut(
        id=str(getattr(board, "id")),
        name=getattr(board, "name"),
        note=getattr(board, "note", None),
        post_ids=[str(r.post_id) for r in pinned],
        posts=[
            BoardFitOut(post_id=post_id, cover_asset_id=covers.get(post_id))
            for post_id in posts
        ],
        refs=[record.ref for record in pinned],
    )


@router.get("", response_model=BoardsResponse)
async def read_boards(db: SessionDep, ctx: AuthDep) -> BoardsResponse:
    """Every board this person has, newest first, each with what is on it.

    Pins come back with the board rather than behind a second request: a
    board with no pictures is not a board, so a client that had to fetch
    them separately would render a list of empty rectangles first.
    """
    boards = await domain.list_boards(db, user_id=ctx.user_id)
    return BoardsResponse(items=[await _out(db, board) for board in boards])


@router.post("", response_model=BoardOut, status_code=status.HTTP_201_CREATED)
async def create_board(payload: BoardIn, db: SessionDep, ctx: AuthDep) -> BoardOut:
    board = await domain.create_board(
        db, user_id=ctx.user_id, name=payload.name or "", note=payload.note
    )
    return await _out(db, board)


@router.patch("/{board_id}", response_model=BoardOut)
async def rename_board(
    board_id: uuid.UUID, payload: BoardIn, db: SessionDep, ctx: AuthDep
) -> BoardOut:
    """Change the name or the note. Omitting either leaves it alone."""
    board = await domain.rename_board(
        db,
        user_id=ctx.user_id,
        board_id=board_id,
        name=payload.name,
        note=payload.note,
    )
    return await _out(db, board)


@router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board(
    board_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> Response:
    """Remove a board and everything on it. 204 either way."""
    await domain.delete_board(db, user_id=ctx.user_id, board_id=board_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{board_id}/posts/{post_id}", response_model=BoardOut)
async def pin_post(
    board_id: uuid.UUID, post_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> BoardOut:
    """Put a fit somebody published on a board.

    404 if the fit is withdrawn, its author is blocked either way, or it
    never existed: the reader cannot tell those apart, and should not.
    """
    await domain.pin(db, user_id=ctx.user_id, board_id=board_id, post_id=post_id)
    board = await domain.get_board(db, user_id=ctx.user_id, board_id=board_id)
    return await _out(db, board)


@router.delete("/{board_id}/posts/{post_id}", response_model=BoardOut)
async def unpin_post(
    board_id: uuid.UUID, post_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> BoardOut:
    """Take a fit off, closing the gap in the arrangement."""
    await domain.unpin(
        db, user_id=ctx.user_id, board_id=board_id, ref=f"post:{post_id}"
    )
    board = await domain.get_board(db, user_id=ctx.user_id, board_id=board_id)
    return await _out(db, board)


@router.put("/{board_id}/order", response_model=PinsResponse)
async def reorder_board(
    board_id: uuid.UUID, payload: ReorderIn, db: SessionDep, ctx: AuthDep
) -> PinsResponse:
    """Set the arrangement.

    Anything on the board but not in the list keeps its relative order after
    everything named, rather than being removed: a partial list means a
    client that knows about fewer pins than exist.
    """
    ordered = await domain.reorder(
        db, user_id=ctx.user_id, board_id=board_id, refs=payload.refs
    )
    return PinsResponse(refs=[record.ref for record in ordered])

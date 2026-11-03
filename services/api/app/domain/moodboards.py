"""Making boards, and putting things on them.

Four rules, each the answer to a way a collection feature goes wrong.

**A name is required and unique per person.** Two boards called "summer" are
two boards nobody can tell apart, and the one somebody pins to is whichever
the query happened to return first.

**Pinning is idempotent.** Tapping a fit twice pins it once. A board that
accumulates duplicates has to be de-duplicated at read time forever after.

**Position is explicit and compacted.** A board is a composition, so order is
a column. Removing the middle pin must not leave a hole that a later insert
silently fills in the wrong place.

**Bounded.** A board with ten thousand pins is a corrupt client rather than an
enthusiastic user, and a person with a thousand boards has a loop somewhere.
Both are refused rather than stored.

**A pin is a fit somebody published.** It used to be either that or a
curated look, with a check constraint and a branch at every caller; the
catalogue is gone and a pin is one thing. Pinning goes through the same
visibility gate the feed uses, so a blocked person's fit cannot be
collected by reading its id out of an old response.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiError
from app.models.moodboard import Moodboard, MoodboardPin

#: The most pins one board may hold.
MAX_PINS = 200

#: The most boards one person may have.
MAX_BOARDS = 100

MAX_NAME = 80
MAX_NOTE = 300


class BoardNotFound(ApiError):
    status_code = 404
    code = "moodboard_not_found"
    default_message = "That board does not exist."


class DuplicateBoardName(ApiError):
    status_code = 409
    code = "moodboard_name_taken"
    default_message = "You already have a board with that name."


class BoardFull(ApiError):
    status_code = 422
    code = "moodboard_full"
    default_message = "That board holds as much as a board can."


class TooManyBoards(ApiError):
    status_code = 422
    code = "too_many_moodboards"
    default_message = "That is more boards than one account may have."


class EmptyName(ApiError):
    status_code = 422
    code = "moodboard_name_required"
    default_message = "A board needs a name."


class PinNotFound(ApiError):
    # Not-found rather than forbidden, for the same reason as a board
    # belonging to somebody else: the three cases a reader cannot tell
    # apart — withdrawn, blocked, never existed — should answer alike.
    status_code = 404
    code = "pin_subject_not_found"
    default_message = "There is nothing there to pin."


def ref_of(record: MoodboardPin) -> str:
    """The string that names what a pin points at."""
    return record.ref


def parse_ref(ref: str) -> uuid.UUID:
    """Read a `ref` back into the fit it names.

    A malformed ref is a not-found rather than a 500: the id came off a
    client that may be out of date, and a bad UUID names nothing. The
    `post:` prefix older clients send is accepted and ignored.
    """
    try:
        return uuid.UUID(ref.removeprefix("post:"))
    except ValueError:
        raise PinNotFound() from None


async def list_boards(
    session: AsyncSession, *, user_id: uuid.UUID
) -> Sequence[Moodboard]:
    """This person's boards, newest first."""
    result = await session.scalars(
        sa.select(Moodboard)
        .where(Moodboard.user_id == user_id)
        .order_by(Moodboard.created_at.desc())
    )
    return result.all()


async def pins(
    session: AsyncSession, *, board_id: uuid.UUID
) -> Sequence[MoodboardPin]:
    """What is on a board, in the order it was arranged."""
    result = await session.scalars(
        sa.select(MoodboardPin)
        .where(MoodboardPin.moodboard_id == board_id)
        .order_by(MoodboardPin.position.asc())
    )
    return result.all()


async def get_board(
    session: AsyncSession, *, user_id: uuid.UUID, board_id: uuid.UUID
) -> Moodboard:
    """The board, if it is this person's. Raises if it is not.

    Not-found rather than forbidden for a board belonging to somebody else:
    distinguishing the two would confirm that a given id exists, which is a
    small leak and an unnecessary one.
    """
    board = await session.scalar(
        sa.select(Moodboard).where(
            Moodboard.id == board_id, Moodboard.user_id == user_id
        )
    )
    if board is None:
        raise BoardNotFound()
    return board


async def create_board(
    session: AsyncSession, *, user_id: uuid.UUID, name: str, note: str | None = None
) -> Moodboard:
    """Make a board."""
    cleaned = name.strip()[:MAX_NAME]
    if not cleaned:
        raise EmptyName()

    count = int(
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(Moodboard)
            .where(Moodboard.user_id == user_id)
        )
        or 0
    )
    if count >= MAX_BOARDS:
        raise TooManyBoards(
            f"{count} boards is already the most one account may have."
        )

    clash = await session.scalar(
        sa.select(Moodboard).where(
            Moodboard.user_id == user_id, Moodboard.name == cleaned
        )
    )
    if clash is not None:
        raise DuplicateBoardName()

    board = Moodboard(
        user_id=user_id,
        name=cleaned,
        note=(note.strip()[:MAX_NOTE] or None) if note is not None else None,
    )
    session.add(board)
    await session.commit()
    await session.refresh(board)
    return board


async def rename_board(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    board_id: uuid.UUID,
    name: str | None = None,
    note: str | None = None,
) -> Moodboard:
    """Change a board's name or note. Omitting either leaves it alone."""
    board = await get_board(session, user_id=user_id, board_id=board_id)

    if name is not None:
        cleaned = name.strip()[:MAX_NAME]
        if not cleaned:
            raise EmptyName()
        if cleaned != board.name:
            clash = await session.scalar(
                sa.select(Moodboard).where(
                    Moodboard.user_id == user_id, Moodboard.name == cleaned
                )
            )
            if clash is not None:
                raise DuplicateBoardName()
        board.name = cleaned

    if note is not None:
        board.note = note.strip()[:MAX_NOTE] or None

    await session.commit()
    await session.refresh(board)
    return board


async def delete_board(
    session: AsyncSession, *, user_id: uuid.UUID, board_id: uuid.UUID
) -> bool:
    """Remove a board and everything on it."""
    board = await session.scalar(
        sa.select(Moodboard).where(
            Moodboard.id == board_id, Moodboard.user_id == user_id
        )
    )
    if board is None:
        return False
    # Pins first, explicitly, rather than relying on a cascade: the cascade
    # is declared on the foreign key and this keeps the behaviour the same on
    # SQLite, where it is off unless somebody remembered to switch it on.
    await session.execute(
        sa.delete(MoodboardPin).where(MoodboardPin.moodboard_id == board_id)
    )
    await session.delete(board)
    await session.commit()
    return True


async def pin(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    board_id: uuid.UUID,
    post_id: uuid.UUID,
) -> MoodboardPin:
    """Put a published fit on a board. Idempotent, appends."""
    await get_board(session, user_id=user_id, board_id=board_id)

    # The same gate the feed reads through. Without it, an id copied out
    # of a response from before a block would still pin.
    from app.domain import feed

    if await feed.one(session, user_id=user_id, post_id=post_id) is None:
        raise PinNotFound()

    existing = await session.scalar(
        sa.select(MoodboardPin).where(
            MoodboardPin.moodboard_id == board_id,
            MoodboardPin.post_id == post_id,
        )
    )
    if existing is not None:
        return existing

    count = int(
        await session.scalar(
            sa.select(sa.func.count())
            .select_from(MoodboardPin)
            .where(MoodboardPin.moodboard_id == board_id)
        )
        or 0
    )
    if count >= MAX_PINS:
        raise BoardFull(f"{count} pins is already the most one board may hold.")

    record = MoodboardPin(moodboard_id=board_id, post_id=post_id, position=count)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def unpin(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    board_id: uuid.UUID,
    ref: str,
) -> bool:
    """Take a fit off a board, and close the gap it leaves.

    Compacting matters: without it, removing the middle pin leaves position
    1 empty, and the next pin appended at `count` collides with an existing
    position. The order then depends on which row the database returns
    first, which is the kind of bug that only shows up on somebody else's
    machine.
    """
    await get_board(session, user_id=user_id, board_id=board_id)
    post_id = parse_ref(ref)

    result = await session.execute(
        sa.delete(MoodboardPin).where(
            MoodboardPin.moodboard_id == board_id,
            MoodboardPin.post_id == post_id,
        )
    )
    if not result.rowcount:
        await session.commit()
        return False

    remaining = (
        await session.scalars(
            sa.select(MoodboardPin)
            .where(MoodboardPin.moodboard_id == board_id)
            .order_by(MoodboardPin.position.asc())
        )
    ).all()
    for index, record in enumerate(remaining):
        record.position = index
    await session.commit()
    return True


async def reorder(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    board_id: uuid.UUID,
    refs: Sequence[str],
) -> Sequence[MoodboardPin]:
    """Set the arrangement.

    Anything on the board but missing from the list keeps its relative order
    after everything named, rather than being dropped: a partial list is a
    client that knows about fewer pins than exist, and silently deleting the
    rest is the worst possible reading of that.
    """
    await get_board(session, user_id=user_id, board_id=board_id)

    current = (
        await session.scalars(
            sa.select(MoodboardPin)
            .where(MoodboardPin.moodboard_id == board_id)
            .order_by(MoodboardPin.position.asc())
        )
    ).all()
    by_ref = {record.ref: record for record in current}

    ordered: list[MoodboardPin] = []
    for ref in refs:
        record = by_ref.pop(ref, None)
        if record is not None:
            ordered.append(record)
    ordered.extend(by_ref.values())

    for index, record in enumerate(ordered):
        record.position = index
    await session.commit()
    return ordered


__all__ = [
    "MAX_BOARDS",
    "MAX_NAME",
    "MAX_NOTE",
    "MAX_PINS",
    "BoardFull",
    "BoardNotFound",
    "DuplicateBoardName",
    "EmptyName",
    "PinNotFound",
    "TooManyBoards",
    "create_board",
    "delete_board",
    "get_board",
    "list_boards",
    "parse_ref",
    "pin",
    "pins",
    "ref_of",
    "rename_board",
    "reorder",
    "unpin",
]

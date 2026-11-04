"""Discover: the board, built from what people here posted.

Replaces a catalogue of generated covers. Every endpoint answers for
*this* reader: their blocks apply, their stated taste reorders, and the
counts are the ones they can see.

**A caption names the clothes.** The author's own words come first and are
never replaced. Where they wrote none, the card shows the description read
off the photograph, which is what makes a fit findable by what is in it
rather than only by the mood somebody typed.

**"Try it on" is a real pipeline run.** It gates the fit, writes a render
row and answers at once; the worker reads the clothes out of the
photograph and draws them on the asker's own avatar. There is no fixture
anywhere in that path.
"""

from __future__ import annotations

import sqlalchemy as sa
import uuid

from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field

from app.deps import AuthDep, SessionDep
from app.domain import comments as comments_domain
from app.domain import feed as domain
from app.domain import fit_descriptions
from app.domain import visual_search
from app.domain import posts as posts_domain
from app.domain import profiles as profile_domain
from app.domain.community import first_name
from app.errors import ApiError
from app.models.media_asset import MediaAsset
from app.models.posts import Post
from app.schemas.posts import PostItemOut
from app.models.user import User
from app.schemas.feed import (
    FitPieceOut,
    CommentIn,
    CommentLikeOut,
    CommentOut,
    CommentsOut,
    FeedItemOut,
    FeedOut,
    FitAuthorOut,
    FitDetailOut,
    DoorOut,
    ExploreOut,
    IdeasOut,
    GroupOut,
    GroupsOut,
    TagFeedOut,
    TagOut,
    TagsOut,
    VisualSearchIn,
    VisualSearchOut,
    TryOnFitOut,
)

router = APIRouter(prefix="/feed", tags=["feed"])


def fit_link(post_id: uuid.UUID) -> str:
    """Where a fit lives, as a link somebody can send.

    Built here rather than in a client so the destination is decided in
    one place.

    A public web page wins when one is configured, because a link
    anybody can open beats one that only works for people who already
    have the app. Otherwise the app's own scheme, which at least opens
    the fit for somebody who does.

    Neither configured returns empty, and a caller shows the picture
    without a link rather than attaching a URL that resolves nowhere.
    The scheme is configuration rather than a literal here: the product
    name lives in `branding.config.js` and nothing in this service
    hardcodes it.
    """
    from app.config import get_settings

    cfg = get_settings()
    base = (cfg.public_web_base_url or "").rstrip("/")
    if base:
        return f"{base}/fit/{post_id}"
    scheme = (cfg.app_link_scheme or "").strip()
    return f"{scheme}://fit/{post_id}" if scheme else ""


async def _liked_groups(db: SessionDep, user_id) -> set[str]:
    """Groups this person said they like, mapped from their taste tags."""
    from app.domain.taste import read_taste

    try:
        taste = await read_taste(db, user_id=user_id)
    except Exception:
        return set()
    aesthetics = list(getattr(taste, "aesthetics", []) or [])
    return set(domain.categorise([a.replace("-", "") for a in aesthetics]))


def _ratio(size: tuple[int | None, int | None] | None) -> float | None:
    """Width over height, when both are known and neither is zero."""
    if size is None:
        return None
    width, height = size
    if not width or not height:
        return None
    return round(width / height, 4)


async def _render(db: SessionDep, entries, *, viewer_id) -> list[FeedItemOut]:
    names: dict = {}
    described: dict = {}
    counted: dict = {}
    covers: dict = {}
    if entries:
        rows = await db.scalars(
            sa.select(User).where(User.id.in_({e.author_id for e in entries}))
        )
        names = {user.id: user for user in rows}
        # One query each for the whole board, never one per tile.
        described = await fit_descriptions.for_posts(
            db, [e.post.id for e in entries]
        )
        counted = await comments_domain.counts(
            db, [e.post.id for e in entries], viewer_id=viewer_id
        )
        # One query for every cover on the board, never one per tile.
        covers = {
            asset_id: (width, height)
            for asset_id, width, height in (
                await db.execute(
                    sa.select(
                        MediaAsset.id, MediaAsset.width, MediaAsset.height
                    ).where(
                        MediaAsset.id.in_(
                            [
                                e.media_asset_ids[0]
                                for e in entries
                                if e.media_asset_ids
                            ]
                        )
                    )
                )
            ).all()
        }
    return [
        FeedItemOut(
            id=entry.post.id,
            author_id=entry.author_id,
            author_name=(
                first_name(names[entry.author_id])
                if entry.author_id in names
                else "Someone"
            ),
            caption=fit_descriptions.shown_caption(
                entry.post, described.get(entry.post.id)
            ),
            #: True when the caption above came from the photograph rather
            #: than from the author, so a client can present it as the
            #: description it is rather than as somebody's words.
            caption_is_described=(
                not (entry.post.caption or "").strip()
                and described.get(entry.post.id) is not None
            ),
            occasion=entry.post.occasion,
            media_asset_ids=entry.media_asset_ids,
            cover_ratio=_ratio(covers.get(entry.media_asset_ids[0]))
            if entry.media_asset_ids
            else None,
            tags=entry.tags,
            groups=entry.groups,
            reactions=entry.reactions,
            saves=entry.saves,
            comments=int(counted.get(entry.post.id, 0)),
            my_reaction=entry.my_reaction,
            saved_by_me=entry.saved_by_me,
            published_at=entry.post.published_at,
        )
        for entry in entries
    ]


@router.get("", response_model=FeedOut)
async def board(
    db: SessionDep,
    ctx: AuthDep,
    group: str | None = None,
) -> FeedOut:
    """Published fits, chosen for this reader. `group` narrows, never filters out.

    **Two paths, deliberately.** With no group the staged recommender
    builds the grid: a walk over the boards people curate, plus what
    is accelerating, plus a slice of unproven pins, blended to a
    target mix and filtered against what this person has already been
    shown (`app/domain/discovery/README.md`).

    A group chip is a different question - "show me everything in
    decor" - and the answer to it should be the whole group in a
    sensible order, not a personalised sample of it. Routing a chip
    through the recommender would make it quietly incomplete, and a
    filter that silently omits things is worse than one that does
    not personalise.
    """
    notes: dict[str, object] = {}
    if group and group != "all":
        entries = await domain.board(
            db,
            user_id=ctx.user_id,
            group=group,
            liked_groups=await _liked_groups(db, ctx.user_id),
        )
        # A group chip answers "show me everything in denim" in one
        # pass, so there is no second page to offer.
        more = False
    else:
        from app.domain.discovery.wiring import seen_store

        entries = await domain.discovered(
            db, user_id=ctx.user_id, seen_store=seen_store(), notes=notes
        )
        # **There is always more, as long as this page had anything.**
        #
        # The board does not end. Walking past the last unseen pin
        # starts a fresh lap in a new order rather than stopping, so
        # the only thing that can stop the scroll is a page with
        # nothing in it - an empty corpus, or a reader who can see
        # none of it. `notes["exhausted"]` still says when a lap
        # turned over; it is a diagnostic, not a stop condition.
        more = bool(entries)

    return FeedOut(
        group=group or "all",
        items=await _render(db, entries, viewer_id=ctx.user_id),
        more=more,
    )


#: How many ids a client may send back as "already shown".
#:
#: Each is 36 characters, so this is about 4KB of query string - well
#: inside every limit and far more history than the shelf needs. Past
#: it the oldest are dropped, which at worst repeats something from
#: several screens ago.
MOST_EXCLUDED = 120


@router.get("/{post_id}/more", response_model=FeedOut)
async def more_under_a_pin(
    post_id: uuid.UUID,
    db: SessionDep,
    ctx: AuthDep,
    exclude: Annotated[list[uuid.UUID], Query()] = [],  # noqa: B006
) -> FeedOut:
    """The next slice of "More to explore" under one pin.

    **The shelf does not end, and neither does the next one.** Opening
    a pin from this shelf opens a page with its own shelf, which pages
    the same way, so a reader can go pin to pin to pin without ever
    reaching a bottom. That is the whole behaviour the board has and
    this page did not: `more` was a fixed twelve computed once with
    the detail.

    **Related first, then anything.** `more_like` ranks by what people
    file this pin with, then by tags, then by group - genuinely about
    *this* pin, and finite. When it runs out the shelf tops up from
    the ordinary recommender rather than stopping, because a reader
    who has scrolled that far is browsing, and more pins is a better
    answer than a wall.

    The reader sends back what they have already been shown. It lives
    on the client because the shelf is per-pin and per-visit: a
    server-side window spanning the session would make opening the
    same pin twice show two different shelves, and the second would be
    worse.
    """
    seen = set(exclude[-MOST_EXCLUDED:])
    entries = await domain.more_like(
        db, user_id=ctx.user_id, post_id=post_id, exclude=seen
    )

    if len(entries) < 6:
        from app.domain.discovery.wiring import seen_store

        topped = await domain.discovered(
            db,
            user_id=ctx.user_id,
            seen_store=seen_store(),
            # Not recorded: this is a shelf under a pin, and letting
            # it eat the Discover board's novelty would mean opening
            # two pins left the board with nothing new in it.
            record=False,
        )
        already = seen | {e.post.id for e in entries} | {post_id}
        entries = entries + [e for e in topped if e.post.id not in already]

    return FeedOut(
        group="more",
        items=await _render(db, entries, viewer_id=ctx.user_id),
        # Only an empty slice ends it, which on a board of hundreds
        # means the reader can see almost none of it.
        more=bool(entries),
    )


class CutOutsOut(BaseModel):
    """The garments cut from a fit, and whether more are coming."""

    pieces: list[FitPieceOut] = Field(default_factory=list)
    #: True while the cut is queued or running, so the client knows to
    #: poll rather than concluding the fit has nothing in it.
    working: bool = False


@router.post("/{post_id}/cut-outs", response_model=CutOutsOut)
async def cut_outs(post_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> CutOutsOut:
    """Make sure this fit's garments have been cut out, and say where it got to.

    **This is what makes try-on fast and cheap.** Dressing a figure
    has two possible mechanics. A photorealistic render describes the
    outfit to an image model and pays it to draw somebody wearing that
    description: fifteen to thirty seconds, a billed call every time,
    and what comes back is a picture of clothes *like* the ones in the
    fit. Compositing cuts each garment out of the fit's own photograph
    and lays it on the mannequin: the clothes are the actual clothes,
    the compositing happens on the phone for nothing, and it is
    instant.

    Compositing needs cut-outs, and none existed - the describe pass
    that produces them had never run against the current board, so
    every try-on fell through to the billed path. Cutting the whole
    board up front would be hundreds of segmentation calls for pins
    nobody has opened. Cutting the one pin somebody actually tapped
    is a handful, it happens once, and every later viewer of that pin
    gets it free.

    Idempotent twice over: the job is keyed on the post, so twenty
    people opening the same fit in the same minute queue one cut, and
    a fit already cut returns its pieces without queueing anything.

    POST because it can start work. It is still safe to call
    repeatedly, which is what a polling client does.
    """
    entry = await domain.one(db, user_id=ctx.user_id, post_id=post_id)
    if entry is None:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )

    cut = await fit_descriptions.pieces_of(db, post_id=post_id)
    if cut:
        return CutOutsOut(pieces=[_piece(row) for row in cut], working=False)

    # Nothing yet. Queue the reading that produces them - unless one
    # is already queued, which `request_description` decides.
    await fit_descriptions.request_description(db, post_id=post_id)
    return CutOutsOut(pieces=[], working=True)


def _piece(row) -> FitPieceOut:
    return FitPieceOut(
        media_asset_id=row.media_asset_id,
        position=row.position,
        name=row.name,
        colour=row.colour,
        category=row.category,
    )


@router.get("/groups", response_model=GroupsOut)
async def groups(db: SessionDep, ctx: AuthDep) -> GroupsOut:
    """The chips above the board, with what is actually moving in each."""
    found = await domain.groups(db, user_id=ctx.user_id)
    return GroupsOut(
        min_people=domain.MIN_TRENDING_PEOPLE,
        items=[
            GroupOut(
                group=g.group, posts=g.posts, people=g.people, trending=g.trending
            )
            for g in found
        ],
    )


@router.get("/saved", response_model=FeedOut)
async def saved(db: SessionDep, ctx: AuthDep) -> FeedOut:
    """Fits you kept, most recently kept first.

    The library's pins are other people's posts rather than entries
    from a catalogue, so they come back in the same shape the board
    uses — same counts, same controls, same object.
    """
    entries = await domain.saved(db, user_id=ctx.user_id)
    return FeedOut(group="saved", items=await _render(db, entries, viewer_id=ctx.user_id))


@router.get("/{post_id}/comments", response_model=CommentsOut)
async def read_comments(
    post_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> CommentsOut:
    """A fit's comments, oldest first.

    Published ones from everybody, plus this reader's own in whatever
    state they are in: a comment that vanished on submission reads as a
    bug and invites a second attempt, so its author sees it waiting.
    """
    try:
        found = await comments_domain.visible(
            db, user_id=ctx.user_id, post_id=post_id
        )
    except comments_domain.FitNotVisible:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return CommentsOut(
        items=[
            CommentOut(
                id=view.comment.id,
                author_id=view.author_id,
                author_name=view.author_name,
                body=view.comment.body,
                state=view.comment.state,
                # The reason is for its author. Nobody else is told a
                # comment was held, or that one exists.
                note=view.comment.screen_note if view.mine else None,
                parent_id=view.comment.parent_id,
                mine=view.mine,
                created_at=view.comment.created_at,
                likes=view.likes,
                liked_by_me=view.liked_by_me,
            )
            for view in found
        ]
    )


@router.put("/comments/{comment_id}/like", response_model=CommentLikeOut)
async def like_comment(
    comment_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> CommentLikeOut:
    """Like a comment. Idempotent: liking twice is liking once.

    Returns the new tally rather than 204, so the row can settle on the
    server's number instead of the one the client guessed.
    """
    try:
        likes = await comments_domain.set_liked(
            db, user_id=ctx.user_id, comment_id=comment_id, liked=True
        )
    except comments_domain.NotYourComment:
        # 404, not 403: a different answer would confirm the id exists.
        raise ApiError(
            "No such comment.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return CommentLikeOut(likes=likes, liked_by_me=True)


@router.delete("/comments/{comment_id}/like", response_model=CommentLikeOut)
async def unlike_comment(
    comment_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> CommentLikeOut:
    """Take a like back. Idempotent, like giving one."""
    try:
        likes = await comments_domain.set_liked(
            db, user_id=ctx.user_id, comment_id=comment_id, liked=False
        )
    except comments_domain.NotYourComment:
        raise ApiError(
            "No such comment.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return CommentLikeOut(likes=likes, liked_by_me=False)


@router.post(
    "/{post_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def write_comment(
    post_id: uuid.UUID, payload: CommentIn, db: SessionDep, ctx: AuthDep
) -> CommentOut:
    """Leave a comment. Held until it has been screened.

    201 with the comment in `pending_review`, not 202: the row exists
    and is theirs to see, which is a created thing rather than an
    accepted request.
    """
    try:
        comment = await comments_domain.write(
            db,
            user_id=ctx.user_id,
            post_id=post_id,
            body=payload.body,
            parent_id=payload.parent_id,
        )
    except comments_domain.FitNotVisible:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    except comments_domain.EmptyComment:
        raise ApiError(
            "Write something first.", status_code=422, code="empty_comment"
        ) from None
    except comments_domain.TooManyPending:
        raise ApiError(
            "You have comments here waiting to be checked. They will "
            "appear shortly.",
            status_code=429,
            code="too_many_pending_comments",
        ) from None

    from app.domain.community import first_name
    from app.models.user import User

    author = await db.get(User, ctx.user_id)
    return CommentOut(
        id=comment.id,
        author_id=comment.user_id,
        author_name=first_name(author) if author else "You",
        body=comment.body,
        state=comment.state,
        note=comment.screen_note,
        parent_id=comment.parent_id,
        mine=True,
        created_at=comment.created_at,
    )


@router.delete(
    "/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_comment(
    comment_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> Response:
    """Remove a comment of yours, or one on a fit of yours. 204 either way.

    Both, because both are owners of the thing: the person who wrote it,
    and the person whose photograph it sits under. Without the second,
    a block would be the only tool available for a single remark.
    """
    try:
        await comments_domain.remove(
            db, user_id=ctx.user_id, comment_id=comment_id
        )
    except comments_domain.NotYourComment:
        # 404, not 403: a different answer would confirm the id exists.
        raise ApiError(
            "No such comment.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _door(door: domain.Door) -> DoorOut:
    return DoorOut(
        kind=door.kind,
        key=door.key,
        label=door.label,
        posts=door.posts,
        cover_asset_id=door.cover_asset_id,
    )


@router.post(
    "/search/visual",
    response_model=VisualSearchOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_visual_search(
    payload: VisualSearchIn, db: SessionDep, ctx: AuthDep
) -> VisualSearchOut:
    """Search by picture. Answers at once with something to poll.

    There is no image index here: the picture is read into words by
    the same model that reads a posted fit, and those words are what
    is searched. The result says what it thought it saw, so the answer
    can be judged rather than only followed.
    """
    try:
        found = await visual_search.start(
            db, user_id=ctx.user_id, asset_id=payload.media_asset_id
        )
    except visual_search.NoSuchPhotograph:
        raise ApiError(
            "No such photograph.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return VisualSearchOut(job_id=found.job_id, state=found.state)


@router.get("/search/visual/{job_id}", response_model=VisualSearchOut)
async def read_visual_search(
    job_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> VisualSearchOut:
    """Where a search by picture got to."""
    found = await visual_search.read(db, user_id=ctx.user_id, job_id=job_id)
    if found is None:
        # The same answer for somebody else's search and one that never
        # existed: a job id is guessable.
        raise ApiError(
            "No such search.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    out = VisualSearchOut(
        job_id=found.job_id,
        state=found.state,
        tags=list(found.tags),
        outfit=found.outfit,
        error=found.error,
    )
    if found.state != "succeeded":
        return out

    # **The results, rather than a tag to go and look up.**
    #
    # This used to hand back words and let the client jump to one
    # tag's page - and when no tag matched, the client showed an
    # alert saying "nothing to go on" and left the person where they
    # started. That is the worst answer available to somebody who
    # opened a camera, framed a shot and waited nine seconds.
    #
    # `loosely` is the half that matters: pins ranked by what they
    # are *of*, on the vectors Discover already uses. A photograph of
    # rings on a hand finds the hand-accessory pins. No model call -
    # the reading is paid for and the vectors are stored.
    from app.domain import visual_matches

    found_pins = await visual_matches.matches(
        db,
        user_id=ctx.user_id,
        tags=list(found.tags),
        pieces=list(found.pieces),
    )
    out.subject = found_pins.subject
    if found_pins.close:
        out.close = await _render(
            db,
            await domain.by_ids(db, user_id=ctx.user_id, ids=found_pins.close),
            viewer_id=ctx.user_id,
        )
    if found_pins.loosely:
        out.loosely = await _render(
            db,
            await domain.by_ids(db, user_id=ctx.user_id, ids=found_pins.loosely),
            viewer_id=ctx.user_id,
        )
    return out


@router.get("/explore", response_model=ExploreOut)
async def explore(db: SessionDep, ctx: AuthDep) -> ExploreOut:
    """Categories to browse, each wearing a real fit.

    Declared before `/{post_id}` for the same reason `/tags` is: a path
    parameter typed as a UUID would reject the literal word with a 422
    rather than falling through to this.
    """
    for_you, popular = await domain.explore(
        db,
        user_id=ctx.user_id,
        liked_groups=await _liked_groups(db, ctx.user_id),
    )
    return ExploreOut(
        for_you=[_door(door) for door in for_you],
        popular=[_door(door) for door in popular],
    )


@router.get("/ideas", response_model=IdeasOut)
async def ideas(db: SessionDep, ctx: AuthDep, limit: int = 6) -> IdeasOut:
    """Tags this reader keeps reaching for, each wearing a real fit.

    Declared before `/{post_id}` for the same reason `/tags` is: a path
    parameter typed as a UUID would reject the literal word with a 422
    rather than falling through to this.

    Ranked by what they saved and reacted to. `explore`'s first row is
    ranked by what they *said*, deliberately; this is the other signal,
    and the two are allowed to disagree.
    """
    found = await domain.ideas(
        db, user_id=ctx.user_id, limit=max(1, min(limit, 12))
    )
    return IdeasOut(items=[_door(door) for door in found])


@router.get("/tags", response_model=TagsOut)
async def tags(
    db: SessionDep,
    ctx: AuthDep,
    q: str | None = None,
    limit: int = 30,
) -> TagsOut:
    """The tags with the most fits under them, or the ones matching `q`.

    With `q` this is the type-ahead under the search field, and the
    suggestions are the app's own hashtags rather than a guessed
    vocabulary: every row offered has fits behind it.

    Declared before `/{post_id}`, and that ordering is load-bearing: a
    path parameter typed as a UUID would reject the literal word `tags`
    with a 422 rather than falling through to this.
    """
    found = await domain.popular_tags(
        db, user_id=ctx.user_id, starting=q, limit=max(1, min(limit, 50))
    )
    return TagsOut(items=[TagOut(tag=tag, posts=count) for tag, count in found])


@router.get("/tags/{tag}", response_model=TagFeedOut)
async def tag_feed(
    tag: str,
    db: SessionDep,
    ctx: AuthDep,
    photographs_only: bool = False,
) -> TagFeedOut:
    """Every fit carrying one hashtag, best first.

    A tag nobody has used is an empty page rather than a 404: it is a
    search that found nothing, which is a true answer, and a missing
    page would be wrong about a tag somebody is about to use.

    Not reordered by stated taste. Somebody who tapped a tag has already
    said what they want, and ranking their own search by a profile would
    be overruling them.
    """
    normalised = domain.normalise_tag(tag)
    if normalised is None:
        return TagFeedOut(tag=tag.strip().lstrip("#").lower()[:30])
    entries = await domain.by_tag(
        db, user_id=ctx.user_id, tag=normalised, photographs_only=photographs_only
    )
    return TagFeedOut(
        tag=normalised,
        items=await _render(db, entries, viewer_id=ctx.user_id),
        related=await domain.related_tags(db, user_id=ctx.user_id, tag=normalised),
    )


@router.get("/{post_id}", response_model=FitDetailOut)
async def detail(post_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> FitDetailOut:
    """One fit, its author, and what to look at next.

    The detail screen's whole payload in one request: three round trips
    to draw one screen is three chances to show it half-built.
    """
    entry = await domain.one(db, user_id=ctx.user_id, post_id=post_id)
    if entry is None:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        )
    rendered = await _render(db, [entry], viewer_id=ctx.user_id)
    author = await db.get(User, entry.author_id)
    profile = await profile_domain.get(db, user_id=entry.author_id)
    more = await domain.more_like(db, user_id=ctx.user_id, post_id=post_id)

    # The author's own two controls depend on this, and on nothing
    # else: an author opening their fit from the board, from a search
    # result or from their profile gets the same menu, because the
    # question is who posted it and not how it was reached.
    mine = entry.author_id == ctx.user_id
    post = await db.get(Post, post_id) if mine else None

    # What the look is made of, for the button that offers to shop it.
    # One query for one post, on the one page that reads them.
    pieces = await posts_domain.items_for(db, post_id=post_id)
    # The garments themselves, cut from this fit's own photograph.
    # Whether their bytes come down is asked per request by the
    # media gate; these are only the ids and their labels.
    cut = await fit_descriptions.pieces_of(db, post_id=post_id)

    return FitDetailOut(
        link=fit_link(post_id),
        fit=rendered[0],
        mine=mine,
        pieces=[_piece(row) for row in cut],
        items=[
            PostItemOut(
                kind=piece.kind,  # type: ignore[arg-type]
                category_id=piece.category_id,
                colour=piece.colour,
                title=piece.title,
                brand=piece.brand,
                retailer=piece.retailer,
                price_minor=piece.price_minor,
                currency=piece.currency,
                source_url=piece.source_url,
            )
            for piece in pieces
        ],
        # Only ever to the author. A stranger cannot see a private fit
        # at all, so there is nothing here to tell them.
        visibility=(post.visibility if post is not None else None),
        author=FitAuthorOut(
            user_id=entry.author_id,
            name=first_name(author) if author else "Someone",
            handle=profile.handle if profile else None,
            # The approved bio only: this is a stranger's view of them.
            bio=profile_domain.public_bio(profile),
            followed=await _follows(db, viewer_id=ctx.user_id, author_id=entry.author_id),
            website=_website(profile),
        ),
        more=await _render(db, more, viewer_id=ctx.user_id),
    )


@router.put("/{post_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
async def hide_fit(post_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> Response:
    """Stop showing one fit on your board. 204 either way.

    Smaller than a block on purpose: not wanting one photograph again
    is not the same as not wanting its author anywhere, and offering
    only the larger tool makes people reach for it.
    """
    await domain.hide(db, user_id=ctx.user_id, post_id=post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{post_id}/hide", status_code=status.HTTP_204_NO_CONTENT)
async def unhide_fit(post_id: uuid.UUID, db: SessionDep, ctx: AuthDep) -> Response:
    """Change your mind. 204 either way."""
    await domain.unhide(db, user_id=ctx.user_id, post_id=post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{post_id}/try-on",
    response_model=TryOnFitOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def try_on_fit(
    post_id: uuid.UUID, db: SessionDep, ctx: AuthDep
) -> TryOnFitOut:
    """Put the outfit in this fit on your own avatar.

    202 with a render to poll, like every other paid call here: reading
    the clothes out of the photograph and drawing them on somebody takes
    the better part of a minute between them, and both run on a worker.

    404 when the fit is withdrawn, its author is blocked either way, or it
    never existed. The reader cannot tell those apart and should not.
    """
    try:
        render = await fit_descriptions.try_on(
            db, user_id=ctx.user_id, post_id=post_id
        )
    except fit_descriptions.FitNotVisible:
        raise ApiError(
            "No such fit.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
        ) from None
    return TryOnFitOut(
        render_id=render.id,
        state=render.state,
        #: Empty on the first try of a fit nobody has read. The worker
        #: fills it in, and the render carries it once it is ready.
        outfit=render.outfit,
    )


def _website(profile) -> str | None:
    """The address behind their `website` link, or nothing.

    Through `address_for`, which builds from a table: the stored value
    is a bare host and this is the only thing that turns it into a URL,
    so a profile field cannot become an open redirect.
    """
    handle = (profile.links or {}).get("website") if profile else None
    return profile_domain.address_for("website", handle) if handle else None


async def _follows(db: SessionDep, *, viewer_id, author_id) -> bool:
    from app.models.follow import Follow

    found = await db.scalar(
        sa.select(Follow.followee_id).where(
            Follow.follower_id == viewer_id, Follow.followee_id == author_id
        )
    )
    return found is not None

"""Discover, built from what people here actually posted.

**The catalogue was a placeholder and this replaces it.** Discover used
to be thirty-five generated covers of invented people wearing invented
clothes. They were honest about being generated and they were never the
point: an app about what people wear should show what people here wore.
So the board is now published fits, and the collections are groups those
fits fall into rather than a fixed set they are matched against.

**A fit lands in a group by its hashtags, not by a model's guess.** The
author wrote `#streetwear`; that is a statement of intent by the person
who put the outfit together, and it is better evidence than anything
inferred from pixels. :func:`categorise` maps the tags somebody used
onto the app's vocabulary, and a fit with no recognised tag sits in
`all` rather than being forced somewhere.

**Trending is a count of people, not of actions.** One person reacting
five times is one person. The floor is :data:`MIN_TRENDING_PEOPLE`,
below which a group is not reported as trending at all — a leaderboard
of two is a leaderboard that lies.

**Personalisation reorders, it never hides.** Somebody who said they
like `streetwear` sees it first; they still see the same set of fits as
everybody else. The cut to :data:`MAX_ITEMS` is deliberately made
*before* taste is applied, so two people with opposite tastes get the
same board in a different order — a feed that filtered by stated taste
would stop being a way to discover anything.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.moderation import hidden_either_way
from app.models.media_asset import MediaAsset
from app.models.posts import Post, PostHide, PostMedia, PostSave, shown_to_strangers
from app.models.profile import PostReaction, PostTag
from app.models.user import User

#: How far back the board looks. Long enough that a quiet week is not an
#: empty app, short enough that the first screen is not last season.
WINDOW_DAYS = 60

#: Distinct people a group needs before it is called trending.
MIN_TRENDING_PEOPLE = 3

#: Most fits in one response. The board is scrolled, not paged.
MAX_ITEMS = 120

TAG_SPLIT = re.compile(r"[^a-z0-9]+")


def normalise_tag(raw: str) -> str | None:
    """`#StreetWear!` to `streetwear`, or nothing if there is no tag left."""
    cleaned = TAG_SPLIT.sub("", raw.strip().lstrip("#").lower())
    return cleaned[:40] or None


def tags_in(text: str | None) -> list[str]:
    """Every hashtag written in a caption, in order, without repeats."""
    if not text:
        return []
    out: list[str] = []
    for raw in re.findall(r"#(\w+)", text):
        tag = normalise_tag(raw)
        if tag and tag not in out:
            out.append(tag)
    return out


#: The app's own vocabulary, and the tags people actually write for each.
#:
#: **Synonyms are listed rather than stemmed.** `gym`, `workout` and
#: `activewear` are one group to a person and three strings to a
#: computer, and a stemmer would still miss all three. A table is
#: boring, correct, and can be extended by somebody who knows clothes
#: rather than somebody who knows linguistics.
GROUP_TAGS: dict[str, tuple[str, ...]] = {
    "streetwear": ("streetwear", "street", "hypebeast", "skater", "y2k", "grunge"),
    "workout": ("workout", "gym", "activewear", "athleisure", "running", "sportswear"),
    "office": ("office", "work", "workwear", "corporate", "business", "tailoring", "officesiren"),
    "evening": ("evening", "night", "nightout", "datenight", "cocktail", "blacktie", "formal"),
    "minimal": ("minimal", "minimalist", "cleangirl", "quietluxury", "capsule", "basics", "monochrome"),
    "vintage": ("vintage", "thrift", "thrifted", "secondhand", "retro", "archive", "heritage"),
    "romantic": ("romantic", "coquette", "balletcore", "feminine", "softgirl", "lace"),
    "outdoors": ("outdoors", "gorpcore", "hiking", "techwear", "utility", "outdoor"),
    "occasion": ("wedding", "weddingguest", "party", "festival", "graduation", "birthday"),
    "denim": ("denim", "jeans", "doubledenim", "indigo"),
    # Added from the operator's own folders: these are categories people
    # here actually organise by, and leaving them out put real posts in
    # no group at all.
    "casual": ("casual", "everyday", "weekend", "relaxed"),
    "modest": ("modest", "modestfashion", "covered", "hijabi", "abaya"),
    "heritage": ("heritage", "ankara", "african", "kitenge", "kente", "traditional"),
}

#: Reverse index, built once.
_GROUP_BY_TAG: dict[str, str] = {
    tag: group for group, tags in GROUP_TAGS.items() for tag in tags
}

#: Shown above the board, in this order. `all` always leads.
GROUPS: tuple[str, ...] = ("all", *GROUP_TAGS)


def categorise(tags: list[str]) -> list[str]:
    """Which groups a set of hashtags puts a fit in. Possibly none."""
    out: list[str] = []
    for tag in tags:
        group = _GROUP_BY_TAG.get(tag)
        if group and group not in out:
            out.append(group)
    return out


@dataclass
class FeedPost:
    """One fit on the board, with the counts that rank it."""

    post: Post
    author_id: uuid.UUID
    tags: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    reactions: int = 0
    saves: int = 0
    #: The photographs, in the order the author arranged them.
    media_asset_ids: list[uuid.UUID] = field(default_factory=list)
    #: What this reader did with it, so the controls render their state.
    my_reaction: str | None = None
    saved_by_me: bool = False


async def _counts(
    db: AsyncSession, post_ids: list[uuid.UUID], *, viewer_id: uuid.UUID
) -> tuple[dict, dict, dict, set]:
    if not post_ids:
        return {}, {}, {}, set()

    reactions = dict(
        (
            await db.execute(
                sa.select(PostReaction.post_id, sa.func.count())
                .where(PostReaction.post_id.in_(post_ids))
                .group_by(PostReaction.post_id)
            )
        ).all()
    )
    saves = dict(
        (
            await db.execute(
                sa.select(PostSave.post_id, sa.func.count())
                .where(PostSave.post_id.in_(post_ids))
                .group_by(PostSave.post_id)
            )
        ).all()
    )
    mine = dict(
        (
            await db.execute(
                sa.select(PostReaction.post_id, PostReaction.kind).where(
                    PostReaction.post_id.in_(post_ids),
                    PostReaction.user_id == viewer_id,
                )
            )
        ).all()
    )
    saved = set(
        await db.scalars(
            sa.select(PostSave.post_id).where(
                PostSave.post_id.in_(post_ids), PostSave.user_id == viewer_id
            )
        )
    )
    return reactions, saves, mine, saved


async def _media(db: AsyncSession, post_ids: list[uuid.UUID]) -> dict:
    """Photographs per post, in the author's order.

    Fetched with the board rather than per card: a feed that asks for
    each post's pictures separately is a hundred and twenty round trips
    to draw one screen.
    """
    if not post_ids:
        return {}
    rows = (
        await db.execute(
            sa.select(PostMedia.post_id, PostMedia.media_asset_id)
            .where(PostMedia.post_id.in_(post_ids))
            .order_by(PostMedia.position)
        )
    ).all()
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for post_id, asset_id in rows:
        out.setdefault(post_id, []).append(asset_id)
    return out


async def _tags(db: AsyncSession, post_ids: list[uuid.UUID]) -> dict:
    if not post_ids:
        return {}
    rows = (
        await db.execute(
            sa.select(PostTag.post_id, PostTag.tag).where(PostTag.post_id.in_(post_ids))
        )
    ).all()
    out: dict[uuid.UUID, list[str]] = {}
    for post_id, tag in rows:
        out.setdefault(post_id, []).append(tag)
    return out


def score(entry: FeedPost, *, now: datetime, liked_groups: set[str]) -> float:
    """How high a fit sits on this person's board.

    **Engagement, then freshness, then fit to stated taste.** A reaction
    is a stronger signal than a save — it is public and it costs the
    person something — so it is weighted above one. Age decays over the
    window rather than cutting off, so a very good fit from last month
    still outranks a mediocre one from today. Taste adds, it never
    subtracts: this reorders the board, it does not filter it.
    """
    published = entry.post.published_at or entry.post.created_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - published).total_seconds() / 86_400)
    freshness = max(0.0, 1.0 - age_days / WINDOW_DAYS)

    engagement = entry.reactions * 2.0 + entry.saves * 1.0
    taste = 3.0 if liked_groups.intersection(entry.groups) else 0.0
    return engagement + freshness * 4.0 + taste



def visible_author(viewer_id: uuid.UUID):
    """Fits whose author has not gone private, plus your own either way.

    **One clause, used by every stranger-facing read.** Going private
    says "nobody but me sees my fits", and a switch that hid somebody
    from their own page while leaving their photographs on Discover,
    under every tag they used and on the face of a category tile would
    not be that - it would be a settings screen with an opinion.

    Not an unpublish: nothing is deleted and nothing is re-screened.
    The rows stay exactly where they were and the reads stop returning
    them, which is what makes going public again immediate.

    Your own are always yours: a private account must still see its own
    work everywhere the app shows work.
    """
    from app.models.profile import Profile

    return sa.or_(
        Post.user_id == viewer_id,
        Post.user_id.not_in(
            sa.select(Profile.user_id).where(
                Profile.private.is_(True), Profile.deleted_at.is_(None)
            )
        ),
    )


async def hidden_posts(db: AsyncSession, *, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Fits this person asked not to see again.

    Read once per board rather than joined per row: the set is small
    and a `NOT IN` over it is cheaper than a left join on every query
    that shows a fit.
    """
    rows = await db.scalars(
        sa.select(PostHide.post_id).where(PostHide.user_id == user_id)
    )
    return set(rows)


async def hide(db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
    """Stop showing one fit to one person. Idempotent."""
    existing = await db.get(PostHide, (user_id, post_id))
    if existing is not None:
        return
    db.add(PostHide(user_id=user_id, post_id=post_id))
    await db.commit()


async def unhide(db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
    """Change your mind. Idempotent in this direction too."""
    await db.execute(
        sa.delete(PostHide).where(
            PostHide.user_id == user_id, PostHide.post_id == post_id
        )
    )
    await db.commit()


async def board(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    group: str | None = None,
    liked_groups: set[str] | None = None,
    now: datetime | None = None,
) -> list[FeedPost]:
    """The Discover board: published fits, ranked for this reader.

    Everything published is eligible, not only people they follow — this
    is discovery, and a feed of people you already chose is the
    Community tab.
    """
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=WINDOW_DAYS)
    hidden = await hidden_either_way(db, user_id=user_id)
    # Fits this person asked not to see again. A smaller tool than a
    # block, and the board has to honour it or the control does nothing.
    skipped = await hidden_posts(db, user_id=user_id)

    # Joined to `users` so a deleted account's fits leave the board with
    # it. Without the join they stayed discoverable: the post rows are
    # untouched by account deletion, and "published" is a fact about the
    # post rather than about whether its author is still here.
    query = (
        sa.select(Post)
        .join(User, User.id == Post.user_id)
        .where(
            shown_to_strangers(),
            Post.published_at >= cutoff,
            User.deleted_at.is_(None),
            visible_author(user_id),
        )
        .order_by(Post.published_at.desc())
        .limit(MAX_ITEMS * 2)
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    if skipped:
        query = query.where(Post.id.not_in(skipped))

    posts = list(await db.scalars(query))
    if not posts:
        return []

    ids = [post.id for post in posts]
    tags = await _tags(db, ids)
    media = await _media(db, ids)
    reactions, saves, mine, saved = await _counts(db, ids, viewer_id=user_id)

    entries = []
    for post in posts:
        post_tags = tags.get(post.id, [])
        entries.append(
            FeedPost(
                post=post,
                author_id=post.user_id,
                tags=post_tags,
                groups=categorise(post_tags),
                media_asset_ids=media.get(post.id, []),
                reactions=int(reactions.get(post.id, 0)),
                saves=int(saves.get(post.id, 0)),
                my_reaction=mine.get(post.id),
                saved_by_me=post.id in saved,
            )
        )

    if group and group != "all":
        entries = [entry for entry in entries if group in entry.groups]

    # **Membership first, then order.** The cut to `MAX_ITEMS` is made
    # on the taste-independent score, so two people with different
    # tastes get the same set of fits; taste then decides the order
    # within it. Ranking and cutting in one pass looked equivalent and
    # was not: with more posts than the cap, it let stated taste push
    # other people's fits off the end of the board, which is filtering
    # by taste wearing a different hat.
    entries.sort(key=lambda e: score(e, now=moment, liked_groups=set()), reverse=True)
    entries = _keep(entries, now=moment)

    liked = liked_groups or set()
    if liked:
        entries.sort(key=lambda e: score(e, now=moment, liked_groups=liked), reverse=True)
    return entries


async def discovered(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    size: int = 40,
    seen_store=None,
    now: datetime | None = None,
    record: bool = True,
    notes: dict[str, object] | None = None,
) -> list[FeedPost]:
    """The Discover board, built by the staged recommender.

    **The same `FeedPost` list `board` returns**, so the router, the
    renderer and the client contract are untouched. What changes is
    how the set is chosen and ordered: `board` scores everything
    published in a fortnight, this retrieves from four sources and
    blends them to a target mix. See `app/domain/discovery/README.md`.

    The pipeline's order is kept exactly. Re-sorting its output by
    `score` here would undo the blending - the quotas decide the mix
    and the interleave decides where each source lands, and a sort
    afterwards throws both away and leaves a ranked list again.
    """
    from app.domain.discovery.pipeline import discover

    picks = await discover(
        db,
        user_id=user_id,
        size=size,
        seen_store=seen_store,
        now=now,
        record=record,
        # Carried straight through: the router needs to know whether
        # the corpus has wrapped so it can tell the client to stop
        # asking for more.
        notes=notes,
    )
    if not picks:
        return []

    order = {pick.post_id: at for at, pick in enumerate(picks)}
    found = (
        await db.scalars(sa.select(Post).where(Post.id.in_(list(order))))
    ).all()

    post_ids = [post.id for post in found]
    reactions, saves, mine, saved = await _counts(
        db, post_ids, viewer_id=user_id
    )
    media = await _media(db, post_ids)
    tags = await _tags(db, post_ids)

    entries = [
        FeedPost(
            post=post,
            author_id=post.user_id,
            tags=tags.get(post.id, []),
            groups=categorise(tags.get(post.id, [])),
            media_asset_ids=media.get(post.id, []),
            reactions=int(reactions.get(post.id, 0)),
            saves=int(saves.get(post.id, 0)),
            my_reaction=mine.get(post.id),
            saved_by_me=post.id in saved,
        )
        for post in found
    ]
    entries.sort(key=lambda e: order[e.post.id])
    return entries


#: How new a fit has to be to be given a place regardless of score.
FRESH_HOURS = 48

#: The most of the board those places may take.
#:
#: A cap, because without one a busy hour would be the whole board and
#: everything else anybody follows would vanish for a day.
FRESH_SLOTS = 20


def _keep(entries: list[FeedPost], *, now: datetime) -> list[FeedPost]:
    """The fits that make the board, newest guaranteed a place.

    **This exists because the board had a deadlock.** `score` adds
    unbounded engagement to a freshness term capped at 4.0, so a fit
    posted a minute ago scored about 4 and lost to anything with two
    reactions on it. With more posts than the cap, a new fit never
    reached the board - and nothing on nobody's board is ever reacted
    to, so it never would. Posting into silence, permanently.

    Ranking still decides the order and almost all of the membership.
    This only promises that something posted in the last couple of
    days is not cut purely for being new, which is the difference
    between a board and an archive.
    """
    if len(entries) <= MAX_ITEMS:
        return entries

    kept = entries[:MAX_ITEMS]
    in_kept = {entry.post.id for entry in kept}

    def hours_old(entry: FeedPost) -> float:
        published = entry.post.published_at or entry.post.created_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return (now - published).total_seconds() / 3600.0

    # Newest first, so a burst promotes the newest of it.
    missed = sorted(
        (
            entry
            for entry in entries[MAX_ITEMS:]
            if entry.post.id not in in_kept and hours_old(entry) <= FRESH_HOURS
        ),
        key=hours_old,
    )[:FRESH_SLOTS]
    if not missed:
        return kept

    # They displace the lowest-scoring of what was kept, so the board
    # stays the same size.
    return kept[: MAX_ITEMS - len(missed)] + missed


async def saved(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> list[FeedPost]:
    """Fits this person kept, most recently kept first.

    **The library's pins are other people's posts**, not entries from a
    catalogue. What somebody keeps off Discover is a fit a real person
    put together, so it is the same object here as it is there — which
    is why this returns the same shape the board does, counts and all.

    Not windowed: a pin is a deliberate act and keeping it for sixty
    days would be throwing away somebody's library on a timer. Blocks
    still apply, so keeping a fit and later blocking its author removes
    it from view without deleting the keep.
    """
    # No timestamp is read here, deliberately: this list is
    # explicitly not windowed, as the docstring says, so there is
    # nothing to compare one against. `now` stays in the signature
    # so every feed function is called the same way.
    hidden = await hidden_either_way(db, user_id=user_id)

    query = (
        sa.select(Post, PostSave.created_at.label("kept_at"))
        .join(PostSave, PostSave.post_id == Post.id)
        .join(User, User.id == Post.user_id)
        .where(
            PostSave.user_id == user_id,
            shown_to_strangers(),
            User.deleted_at.is_(None),
            visible_author(user_id),
        )
        .order_by(PostSave.created_at.desc())
        .limit(MAX_ITEMS)
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))

    rows = (await db.execute(query)).all()
    posts = [row[0] for row in rows]
    if not posts:
        return []

    ids = [post.id for post in posts]
    tags = await _tags(db, ids)
    media = await _media(db, ids)
    reactions, saves, mine, saved_ids = await _counts(db, ids, viewer_id=user_id)
    return [
        FeedPost(
            post=post,
            author_id=post.user_id,
            tags=tags.get(post.id, []),
            groups=categorise(tags.get(post.id, [])),
            media_asset_ids=media.get(post.id, []),
            reactions=int(reactions.get(post.id, 0)),
            saves=int(saves.get(post.id, 0)),
            my_reaction=mine.get(post.id),
            saved_by_me=True,
        )
        for post in posts
    ]


async def one(
    db: AsyncSession, *, user_id: uuid.UUID, post_id: uuid.UUID
) -> FeedPost | None:
    """A single fit, if this reader may see it.

    Blocks and deletions apply exactly as they do on the board, and the
    refusal is the same for all three cases — not yours, not published,
    never existed — so a 404 confirms nothing.
    """
    hidden = await hidden_either_way(db, user_id=user_id)
    post = await db.scalar(
        sa.select(Post)
        .join(User, User.id == Post.user_id)
        .where(
            Post.id == post_id,
            shown_to_strangers(),
            User.deleted_at.is_(None),
            visible_author(user_id),
        )
    )
    if post is None or post.user_id in hidden:
        return None

    ids = [post.id]
    tags = (await _tags(db, ids)).get(post.id, [])
    media = (await _media(db, ids)).get(post.id, [])
    reactions, saves, mine, saved_ids = await _counts(db, ids, viewer_id=user_id)
    return FeedPost(
        post=post,
        author_id=post.user_id,
        tags=tags,
        groups=categorise(tags),
        media_asset_ids=media,
        reactions=int(reactions.get(post.id, 0)),
        saves=int(saves.get(post.id, 0)),
        my_reaction=mine.get(post.id),
        saved_by_me=post.id in saved_ids,
    )


async def more_like(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    post_id: uuid.UUID,
    limit: int = 12,
    exclude: set[uuid.UUID] | None = None,
) -> list[FeedPost]:
    """Fits that look like this one.

    `exclude` is what the reader has already been shown under this
    pin, so the shelf can be paged: ask again with everything so far
    and the next batch continues rather than repeating. It is passed
    in rather than remembered here because the shelf is per-pin and
    per-visit - a seen-filter spanning the whole session would make
    opening a pin twice show two different shelves, and the second
    would be worse.

    **What people file it with, then hashtags, then the group.**

    This used to lead with shared hashtags, on the reasoning that
    `#cargos #grey #loafers` says more than a group does. That is
    true when the tags are right and catastrophic when they are not,
    and the failure was not hypothetical: a photograph of a boucle
    bed was posted captioned "Wedding guest, not upstaging anybody"
    and tagged `#occasion #party #weddingguest`, so this function
    offered a shelf of eveningwear under a picture of a couch. The
    ranking was working perfectly on a label that lied.

    So the first signal is now board co-occurrence - how often other
    people have put this pin and another on the same board.
    Somebody saving a couch files it with rooms whatever its caption
    says, because they are looking at the picture. It is an
    independent opinion and it cannot be set by the uploader.

    Hashtags still rank, second, with each one weighted by whether
    the boards around this pin agree it applies
    (`discovery.annotate`). A tag essentially nothing nearby shares
    is discounted rather than deleted - the author may be right and
    the crowd early.

    **Then the group, then the board.** A pin nobody has saved yet
    has no co-occurrence and no consensus, so it falls through to
    tags at full weight, which is the old behaviour and the correct
    one when there is no second opinion to be had.
    """
    seed = await one(db, user_id=user_id, post_id=post_id)
    everything = await board(db, user_id=user_id)
    # Never the pin itself, and never what this shelf has already
    # shown - the second is what lets the caller ask for more.
    skip = {post_id} | (exclude or set())
    pool = [entry for entry in everything if entry.post.id not in skip]
    if seed is None:
        return pool[:limit]

    from app.domain.discovery import annotate, subject as subjects
    from app.domain.discovery.graph import neighbours
    from app.domain.discovery.store import cached_graph
    from app.models.post_vision import PostVisionRow

    graph = await cached_graph(db)

    # **What the photographs are of, which no author can write.**
    #
    # Read before anything is ranked, because this is a gate rather
    # than a weight: a couch and a cream dress are genuinely close on
    # every other signal, and the only correct answer is that neither
    # may sit under the other. Tags cannot express it and a cosine
    # cannot either.
    #
    # Pins with no reading yet are not excluded. A backfill in
    # progress, or a vendor outage, must not empty the shelf - those
    # fall through to the co-occurrence and tag ranking below, which
    # is exactly the behaviour before this existed.
    wanted_ids = [entry.post.id for entry in pool] + [post_id]
    readings = {
        row.post_id: row
        for row in (
            await db.scalars(
                sa.select(PostVisionRow).where(
                    PostVisionRow.post_id.in_(wanted_ids)
                )
            )
        ).all()
    }
    mine = readings.get(post_id)
    if mine is not None:
        allowed_pool = [
            entry
            for entry in pool
            if (seen_as := readings.get(entry.post.id)) is None
            or subjects.may_sit_under(mine.subject, seen_as.subject)
        ]
        # Only if it leaves something. A pin whose subject nothing
        # else shares yet would otherwise have a blank shelf, and a
        # blank shelf at the end of a photograph is where somebody
        # stops scrolling.
        if allowed_pool:
            pool = allowed_pool

    # How often each candidate shares a board with this pin. The
    # primary signal, and the one an author cannot write.
    together: dict[uuid.UUID, int] = {}
    if graph:
        for rank, other in enumerate(neighbours(graph, post_id, limit=200)):
            # Stored as a descending score rather than a rank so it
            # combines with the tag score below.
            together[other] = 200 - rank

    # The author's tags, weighed against what the neighbourhood holds.
    reading = annotate.read(
        graph,
        post_id=post_id,
        author_tags=list(seed.tags),
        tags_by_post={entry.post.id: entry.tags for entry in pool},
    )

    wanted_tags = set(seed.tags)
    if together or wanted_tags:
        def looks_like(other_id: uuid.UUID) -> float:
            """How alike the two photographs are, 0 when unread."""
            theirs = readings.get(other_id)
            if mine is None or theirs is None:
                return 0.0
            return subjects.similarity(
                list(mine.vector or []), list(theirs.vector or [])
            )

        scored = [
            (
                together.get(entry.post.id, 0),
                looks_like(entry.post.id),
                annotate.overlap(reading, list(wanted_tags), entry.tags),
                index,
                entry,
            )
            for index, entry in enumerate(pool)
        ]
        # Co-occurrence, then how alike the pictures are, then
        # trusted-tag overlap, then the board's own ranking as the
        # tie-break.
        #
        # Tags last of the three deliberately. They are the only one
        # of the signals that the person being ranked wrote
        # themselves, and the one that was wrong in the case this
        # ordering exists for.
        alike = [
            entry
            for shared_boards, looks, tag_score, _, entry in sorted(
                (
                    row
                    for row in scored
                    if row[0] > 0 or row[1] > 0 or row[2] > 0
                ),
                key=lambda row: (-row[0], -row[1], -row[2], row[3]),
            )
        ]
        if alike:
            # Topped up from the group and then the board, so the shelf
            # is never shorter than it needs to be.
            seen = {entry.post.id for entry in alike}
            rest = [entry for entry in pool if entry.post.id not in seen]
            return (alike + rest)[:limit]

    if seed.groups:
        wanted = set(seed.groups)
        near = [entry for entry in pool if wanted.intersection(entry.groups)]
        if near:
            return near[:limit]
    return pool[:limit]


@dataclass(frozen=True)
class GroupCount:
    group: str
    posts: int
    #: Distinct people who reacted or saved in this group.
    people: int
    trending: bool



#: How many fits a tag page holds. Larger than the board, because a tag
#: is a deliberate search rather than a glance: somebody who tapped
#: `#linen` is looking for linen, and showing them twelve of it would be
#: answering a narrower question than they asked.
MAX_TAG_ITEMS = 120


#: Media kinds a machine drew. A fit built from one of these is a
#: picture of clothes that were never photographed on anybody, which is
#: a real distinction to somebody searching for what an outfit looks
#: like in life - and the only honest basis for a "photographs only"
#: filter, since nothing else on a post records how it was made.
GENERATED_KINDS: tuple[str, ...] = ("avatar", "garment_render", "garment_studio")


async def by_tag(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tag: str,
    photographs_only: bool = False,
    now: datetime | None = None,
) -> list[FeedPost]:
    """Published fits carrying one hashtag, best first.

    **Filtered in the query, not after it.** The board fetches a recent
    slice and narrows it in Python, which is right for a board: it is
    showing what is around. A tag page cannot work that way - most fits
    tagged `#linen` are outside any recent slice, so narrowing one would
    return a nearly empty page for a tag with a hundred posts under it.

    **No recency cutoff.** A tag is an archive. The board has a window
    because a feed of three-month-old fits is a dead feed; a tag page
    with only this week's is a tag page that lies about how much is
    there.

    Ranked by engagement and freshness, and **not** by stated taste:
    somebody who typed a tag has already said what they want, and
    reordering their own search by a profile would be overruling them.
    """
    normalised = normalise_tag(tag)
    if normalised is None:
        return []

    moment = now or datetime.now(timezone.utc)
    hidden = await hidden_either_way(db, user_id=user_id)

    query = (
        sa.select(Post)
        .join(User, User.id == Post.user_id)
        .join(PostTag, PostTag.post_id == Post.id)
        .where(
            PostTag.tag == normalised,
            shown_to_strangers(),
            User.deleted_at.is_(None),
            visible_author(user_id),
        )
        .order_by(Post.published_at.desc())
        .limit(MAX_TAG_ITEMS)
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    if photographs_only:
        # Any generated picture disqualifies the fit, not just the
        # cover: a set whose second frame is a render is still a set
        # somebody is being shown a render in.
        drawn = (
            sa.select(PostMedia.post_id)
            .join(MediaAsset, MediaAsset.id == PostMedia.media_asset_id)
            .where(MediaAsset.kind.in_(GENERATED_KINDS))
        )
        query = query.where(Post.id.not_in(drawn))

    posts = list(await db.scalars(query))
    if not posts:
        return []

    ids = [post.id for post in posts]
    tags = await _tags(db, ids)
    media = await _media(db, ids)
    reactions, saves, mine, saved = await _counts(db, ids, viewer_id=user_id)

    entries = [
        FeedPost(
            post=post,
            author_id=post.user_id,
            tags=tags.get(post.id, []),
            groups=categorise(tags.get(post.id, [])),
            media_asset_ids=media.get(post.id, []),
            reactions=int(reactions.get(post.id, 0)),
            saves=int(saves.get(post.id, 0)),
            my_reaction=mine.get(post.id),
            saved_by_me=post.id in saved,
        )
        for post in posts
    ]
    entries.sort(key=lambda e: score(e, now=moment, liked_groups=set()), reverse=True)
    return entries


async def related_tags(
    db: AsyncSession, *, user_id: uuid.UUID, tag: str, limit: int = 12
) -> list[str]:
    """Tags that appear alongside this one, most shared first.

    What a tag page needs underneath it: somebody who tapped `#linen`
    and found it too broad has somewhere to go, without this having to
    know anything about fashion. Pure co-occurrence.
    """
    normalised = normalise_tag(tag)
    if normalised is None:
        return []

    hidden = await hidden_either_way(db, user_id=user_id)
    mine = sa.select(PostTag.post_id).where(PostTag.tag == normalised)

    query = (
        sa.select(PostTag.tag, sa.func.count().label("n"))
        .join(Post, Post.id == PostTag.post_id)
        .join(User, User.id == Post.user_id)
        .where(
            PostTag.post_id.in_(mine),
            PostTag.tag != normalised,
            shown_to_strangers(),
            User.deleted_at.is_(None),
            visible_author(user_id),
        )
        .group_by(PostTag.tag)
        .order_by(sa.desc("n"))
        .limit(limit)
    )
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    return [row[0] for row in (await db.execute(query)).all()]


#: How much each kind of engagement counts toward "you like this".
#:
#: A save is the strongest thing somebody does to a pin: it is a
#: deliberate act of keeping, and nobody saves by accident. A comment
#: costs effort and is next. A reaction is one tap, which is real but
#: cheap - and a tap is also the signal most easily produced by
#: scrolling, which is why it does not outweigh the other two.
MINE_WEIGHT: dict[str, float] = {"save": 3.0, "comment": 2.0, "reaction": 1.0}

#: The same signals, from the people somebody follows.
#:
#: Worth less than their own, and deliberately not worth nothing. Who
#: you follow is itself a statement of taste, and it is the only signal
#: a new account has that is better than a global popularity count.
#: Kept well below the reader's own so a prolific friend cannot
#: colonise the row.
THEIRS_WEIGHT = 0.4

#: How many tags of engagement to consider. Past this the tail is noise.
ENOUGH_AFFINITY = 24


async def tags_you_engage_with(
    db: AsyncSession, *, user_id: uuid.UUID, limit: int = ENOUGH_AFFINITY
) -> list[tuple[str, float]]:
    """Tags this reader actually acts on, heaviest first.

    **Behaviour, not a questionnaire.** `explore` used to build its
    first row purely from stated taste, on the argument that a stated
    preference is a statement and a click is an accident. That argument
    is sound about a single click and wrong in aggregate: somebody who
    has saved eleven tailoring pins has stated a preference far more
    convincingly than they did by ticking a box at sign-up, and a row
    that ignores all of it feels like the app is not paying attention.
    Changed on the product owner's instruction (2026-11-03).

    Three sources, weighted: what they saved, what they commented on,
    what they reacted to - plus the same from the people they follow,
    at a discount. Every one of them is counted only over pins this
    reader may actually see, the same rule `popular_tags` obeys, so a
    blocked author cannot steer somebody's own shelf.
    """
    from app.models.comment import PostComment
    from app.models.follow import Follow

    hidden = await hidden_either_way(db, user_id=user_id)

    def visible(query):
        query = query.join(Post, Post.id == PostTag.post_id).join(
            User, User.id == Post.user_id
        )
        return query.where(
            shown_to_strangers(),
            User.deleted_at.is_(None),
            visible_author(user_id),
            # `hidden_either_way` returns *user* ids, not post ids -
            # the same clause every other cross-user read uses.
            Post.user_id.not_in(hidden) if hidden else sa.true(),
        )

    #: (table, the column holding the actor, the weight key)
    sources = (
        (PostSave, PostSave.user_id, PostSave.post_id, "save"),
        (PostComment, PostComment.user_id, PostComment.post_id, "comment"),
        (PostReaction, PostReaction.user_id, PostReaction.post_id, "reaction"),
    )

    #: Who this reader follows, as the second ring of the signal.
    followed = sa.select(Follow.followee_id).where(Follow.follower_id == user_id)

    scored: dict[str, float] = {}
    for model, actor, post_col, kind in sources:
        weight = MINE_WEIGHT[kind]
        rows = (
            await db.execute(
                visible(
                    sa.select(
                        PostTag.tag,
                        sa.func.sum(
                            sa.case((actor == user_id, weight), else_=THEIRS_WEIGHT * weight)
                        ).label("score"),
                    ).join(model, post_col == PostTag.post_id)
                )
                .where(sa.or_(actor == user_id, actor.in_(followed)))
                .group_by(PostTag.tag)
            )
        ).all()
        for tag, score in rows:
            scored[tag] = scored.get(tag, 0.0) + float(score or 0.0)

    ordered = sorted(scored.items(), key=lambda pair: (-pair[1], pair[0]))
    return ordered[:limit]


async def popular_tags(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    starting: str | None = None,
    limit: int = 30,
) -> list[tuple[str, int]]:
    """The tags with the most fits under them, for a search screen.

    Counted over what *this* reader can see, so a blocked person's
    prolific tagging does not inflate a number against a page that will
    then come back shorter than it promised.

    **With `starting`, this is the type-ahead.** The suggestions under
    a search field have to come from what people actually tagged -
    offering a word with nothing behind it is a search that promises a
    result and returns the empty state. Matching is on a substring
    rather than a prefix, because garment vocabulary is compound and
    somebody typing "neck" means to find "crewneck"; the ordering puts
    the tags that *begin* with what was typed first, which is the one
    thing a prefix match got right.
    """
    hidden = await hidden_either_way(db, user_id=user_id)
    query = (
        sa.select(PostTag.tag, sa.func.count().label("n"))
        .join(Post, Post.id == PostTag.post_id)
        .join(User, User.id == Post.user_id)
        .where(
            shown_to_strangers(),
            User.deleted_at.is_(None),
            visible_author(user_id),
        )
        .group_by(PostTag.tag)
    )
    typed = (starting or "").strip().lstrip("#").lower()
    if typed:
        # `escape` because `_` is a wildcard in LIKE and a perfectly
        # ordinary character in a hashtag: without it, typing "off_"
        # matches every four-letter tag beginning "off".
        pattern = typed.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        query = query.where(PostTag.tag.like(f"%{pattern}%", escape="!"))
        query = query.order_by(
            sa.case((PostTag.tag.like(f"{pattern}%", escape="!"), 0), else_=1),
            sa.desc("n"),
            PostTag.tag.asc(),
        )
    else:
        query = query.order_by(sa.desc("n"))
    query = query.limit(limit)
    if hidden:
        query = query.where(Post.user_id.not_in(hidden))
    return [(row[0], int(row[1])) for row in (await db.execute(query)).all()]



@dataclass(frozen=True)
class Door:
    """One category tile: what it is, how much is behind it, and a face.

    The face is a real photograph somebody posted, not generated cover
    art. A grid of invented pictures describing user content is a
    catalogue pretending to be a community; a grid of the community's
    own photographs is the thing itself.
    """

    #: `group` for one of this app's own groupings, `tag` for a hashtag
    #: people actually used. Different destinations, so a client has to
    #: be able to tell them apart.
    kind: str
    key: str
    label: str
    posts: int
    #: The media asset to show on the tile, or nothing when the best
    #: post in this category has no photograph.
    cover_asset_id: uuid.UUID | None


def _title(word: str) -> str:
    """A tag as a label. Their word, capitalised, never reworded."""
    return word[:1].upper() + word[1:]


async def _covers(
    db: AsyncSession, post_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """The first photograph on each of these posts."""
    if not post_ids:
        return {}
    rows = (
        await db.execute(
            sa.select(PostMedia.post_id, PostMedia.media_asset_id)
            .join(MediaAsset, MediaAsset.id == PostMedia.media_asset_id)
            .where(
                PostMedia.post_id.in_(post_ids),
                MediaAsset.deleted_at.is_(None),
                MediaAsset.status.in_(("uploaded", "ready")),
            )
            .order_by(PostMedia.post_id, PostMedia.position.asc())
        )
    ).all()
    first: dict[uuid.UUID, uuid.UUID] = {}
    for post_id, asset_id in rows:
        first.setdefault(post_id, asset_id)
    return first


async def doors(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    tags: list[str],
    now: datetime | None = None,
) -> list[Door]:
    """Turn a list of tags into tiles, each wearing its best fit.

    "Best" is the same score the board ranks by, so the picture on a
    tile is the one that would have led that tag's page anyway. A tag
    with nothing visible behind it is dropped rather than shown as an
    empty door.
    """
    moment = now or datetime.now(timezone.utc)
    out: list[Door] = []
    for tag in tags:
        entries = await by_tag(db, user_id=user_id, tag=tag, now=moment)
        if not entries:
            continue
        covers = await _covers(db, [entries[0].post.id])
        out.append(
            Door(
                kind="tag",
                key=tag,
                label=_title(tag),
                posts=len(entries),
                cover_asset_id=covers.get(entries[0].post.id),
            )
        )
    return out


async def explore(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    liked_groups: set[str] | None = None,
    now: datetime | None = None,
) -> tuple[list[Door], list[Door]]:
    """Two rows of doors: what suits this reader, and what is busy.

    **For you comes from what they do, then from what they said.**
    This used to be stated taste alone, on the argument that a
    preference ticked at sign-up is a statement while a click is an
    accident. True of one click; false of a hundred. Somebody who has
    saved eleven tailoring pins and commented on four has said more
    about their taste than the sign-up form ever collected, and a row
    that ignored all of it was the app visibly not paying attention.
    Reversed on the product owner's instruction (2026-11-03).

    The order is deliberate. Engagement leads because it is current and
    specific; stated taste follows because it is what a new account has
    and because somebody who said "tailoring" and has not yet saved
    anything should still see tailoring.

    **Everything is counted over what this reader can see.** A tag kept
    alive by somebody they blocked is not popular for them, and a pin
    they cannot see cannot teach the app what they like.
    """
    moment = now or datetime.now(timezone.utc)
    liked = liked_groups or set()

    counted = await popular_tags(db, user_id=user_id, limit=60)
    ranked = [tag for tag, _ in counted]

    wanted: list[str] = []

    # What they actually act on, and what the people they follow act
    # on, heaviest first.
    for tag, _score in await tags_you_engage_with(db, user_id=user_id):
        if tag not in wanted:
            wanted.append(tag)

    # Then their stated groups, expanded into the tags that feed them,
    # so a tile is a real hashtag page rather than an abstraction.
    for group in sorted(liked):
        for tag in GROUP_TAGS.get(group, ()):
            if tag in ranked and tag not in wanted:
                wanted.append(tag)
    for_you = await doors(db, user_id=user_id, tags=wanted[:8], now=moment)

    # Anything busy that is not already above it. Two rows showing the
    # same tag twice is one row of information.
    shown = {door.key for door in for_you}
    rest = [tag for tag in ranked if tag not in shown]
    popular = await doors(db, user_id=user_id, tags=rest[:8], now=moment)

    # A new account has said nothing, and an empty first row with a
    # full second one reads as broken. The busiest tags stand in.
    if not for_you:
        for_you, popular = popular[:6], popular[6:]
    return for_you, popular


async def ideas(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int = 6,
    now: datetime | None = None,
) -> list[Door]:
    """Tags this person keeps reaching for, as doors into them.

    **Built from what they did.** The fits somebody keeps are the best
    evidence there is of what they would keep next - joined now by the
    pins they comment on and react to, and by what the people they
    follow are doing the same to. `explore` leads with the same signal;
    the two rows differ in what they fall back to, not in what they
    believe.

    Weighted and decayed by `profile.reaches_for`, so a fortnight of
    saving one thing outranks a single tap on another, and last
    month's interest fades rather than ruling for ever.

    **Falls back rather than returning nothing.** A new account has
    kept nothing, and an empty shelf with a heading over it reads as
    broken; the busiest tags they can see stand in until they have a
    history of their own.
    """
    from app.domain.profile import reaches_for

    moment = now or datetime.now(timezone.utc)
    scored = dict(await reaches_for(db, user_id=user_id, now=moment))

    # Comments, reactions, and the same from the people they follow.
    #
    # `reaches_for` counts what they kept, decayed over time, which is
    # the strongest single signal and was the only one here. It misses
    # two things somebody would expect the shelf to notice: the pins
    # they argue with rather than keep, and what the people they chose
    # to follow are keeping. Added on the product owner's instruction
    # (2026-11-03); the decayed save score still leads, because this
    # second signal has no decay and would otherwise slowly swamp it.
    for tag, score in await tags_you_engage_with(db, user_id=user_id):
        scored[tag] = scored.get(tag, 0.0) + score * 0.25

    # Their own, strongest first. Ties broken by name so the shelf does
    # not reshuffle between two requests that saw the same scores.
    wanted = [
        tag for tag, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    ][: limit * 2]

    if len(wanted) < limit:
        counted = await popular_tags(db, user_id=user_id, limit=limit * 3)
        for tag, _ in counted:
            if tag not in wanted:
                wanted.append(tag)

    found = await doors(db, user_id=user_id, tags=wanted, now=moment)
    return found[:limit]


async def groups(
    db: AsyncSession, *, user_id: uuid.UUID, now: datetime | None = None
) -> list[GroupCount]:
    """What is on the board, grouped, with what is actually moving.

    Counted over the same window and the same visibility rules as the
    board, so the chips cannot promise a group the board then cannot
    fill.
    """
    entries = await board(db, user_id=user_id, now=now)
    posts_per: dict[str, int] = {}
    people_per: dict[str, set[uuid.UUID]] = {}

    ids_by_group: dict[str, list[uuid.UUID]] = {}
    for entry in entries:
        for name in entry.groups:
            posts_per[name] = posts_per.get(name, 0) + 1
            ids_by_group.setdefault(name, []).append(entry.post.id)

    for name, ids in ids_by_group.items():
        reactors = set(
            await db.scalars(
                sa.select(PostReaction.user_id).where(PostReaction.post_id.in_(ids))
            )
        )
        savers = set(
            await db.scalars(
                sa.select(PostSave.user_id).where(PostSave.post_id.in_(ids))
            )
        )
        people_per[name] = reactors | savers

    out = [
        GroupCount(
            group=name,
            posts=posts_per[name],
            people=len(people_per.get(name, set())),
            trending=len(people_per.get(name, set())) >= MIN_TRENDING_PEOPLE,
        )
        for name in GROUP_TAGS
        if posts_per.get(name)
    ]
    out.sort(key=lambda g: (not g.trending, -g.people, -g.posts))
    return out


__all__ = [
    "GROUPS",
    "GROUP_TAGS",
    "MAX_ITEMS",
    "MIN_TRENDING_PEOPLE",
    "WINDOW_DAYS",
    "FeedPost",
    "GroupCount",
    "Door",
    "board",
    "by_tag",
    "categorise",
    "groups",
    "hide",
    "hidden_posts",
    "unhide",
    "doors",
    "explore",
    "more_like",
    "popular_tags",
    "related_tags",
    "one",
    "saved",
    "normalise_tag",
    "score",
    "tags_in",
]

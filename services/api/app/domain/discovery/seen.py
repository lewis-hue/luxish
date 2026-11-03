"""What this person has already been shown.

**This is what makes pull-to-refresh mean anything.** Without it a
refresh re-runs the same ranking over the same corpus and returns the
same pins in the same order, and the gesture that is supposed to say
"show me something else" shows the person exactly what they were
already looking at. The usual answer is a rolling impression
history consulted at render time; this is that, scoped to this
app's size.

**Redis, with the feed surviving its absence.** Impressions are
high-write, short-lived and worthless after a few days - the shape
Redis is for, and the app already runs one for Celery. But a feed
that 500s because a cache is down is worse than a feed that repeats
itself, so every call here degrades to "nothing is seen" rather than
raising. That is the opposite of the rule for a moderation gate,
deliberately: an absent screen must fail closed because the cost is
publishing something unchecked, and an absent seen-filter can only
cost somebody a repeated photograph.

**It expires rather than being cleaned up.** A rolling window is what
is wanted - a pin shown four days ago is a reasonable thing to show
again - and a TTL per key expresses that directly, where a sweeper
would be a second mechanism to keep correct.
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

logger = logging.getLogger(__name__)

#: How long an impression suppresses a pin.
#:
#: Three days. Long enough that a daily user does not see the same
#: grid twice, short enough that the catalogue does not run out - at
#: this corpus size a longer window would leave a heavy user with
#: nothing to show, which fails in a more confusing way than
#: repetition.
REMEMBER_SECONDS = 3 * 24 * 60 * 60

#: Cap on how many impressions are kept per person.
#:
#: A bound is not optional: without one, a scripted client could grow
#: one key without limit. Oldest are dropped first.
MOST_REMEMBERED = 3000


class SeenStore(Protocol):
    """What a seen-filter has to do. Two methods, both best-effort."""

    async def seen(self, user_id: uuid.UUID) -> set[uuid.UUID]: ...

    async def note(
        self, user_id: uuid.UUID, post_ids: list[uuid.UUID]
    ) -> None: ...

    async def forget(self, user_id: uuid.UUID) -> None:
        """Start the lap again.

        Called when the board has been walked end to end. Without it
        every later page finds the filter exhausted, relaxes it, and
        re-picks from the same top-ranked pins - so the scroll repeats
        the same handful rather than going round again. Forgetting
        makes the next lap walk forward properly, in a fresh order.
        """
        ...


class InMemorySeen:
    """Process-local, for tests and for a single-process dev stack.

    Explicitly not for a deployment: two API processes would each
    believe a different set of pins had been shown, so a refresh would
    repeat whatever the other process served. Named so the mistake is
    visible at the call site.
    """

    def __init__(self) -> None:
        self._by_user: dict[uuid.UUID, list[uuid.UUID]] = {}

    async def seen(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        return set(self._by_user.get(user_id, []))

    async def note(self, user_id: uuid.UUID, post_ids: list[uuid.UUID]) -> None:
        if not post_ids:
            return
        kept = self._by_user.setdefault(user_id, [])
        known = set(kept)
        kept.extend(p for p in post_ids if p not in known)
        if len(kept) > MOST_REMEMBERED:
            del kept[: len(kept) - MOST_REMEMBERED]

    async def forget(self, user_id: uuid.UUID) -> None:
        self._by_user.pop(user_id, None)


class RedisSeen:
    """A sorted set per person, scored by when the pin was shown.

    Sorted rather than a plain set so the cap can drop the oldest
    impressions instead of an arbitrary slice, and so the window can
    be trimmed by time as well as by count.
    """

    def __init__(self, client, *, clock=None) -> None:
        self._redis = client
        import time

        self._clock = clock or time.time

    def _key(self, user_id: uuid.UUID) -> str:
        return f"seen:{user_id}"

    async def seen(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        try:
            cutoff = self._clock() - REMEMBER_SECONDS
            raw = await self._redis.zrangebyscore(
                self._key(user_id), cutoff, "+inf"
            )
        except Exception as caught:
            # Degrade to "nothing is seen". A repeated photograph is a
            # smaller failure than a feed that will not load.
            logger.warning("seen-filter unavailable, not filtering: %s", caught)
            return set()
        out: set[uuid.UUID] = set()
        for item in raw or []:
            try:
                out.add(uuid.UUID(item.decode() if isinstance(item, bytes) else item))
            except (ValueError, AttributeError):
                continue
        return out

    async def note(self, user_id: uuid.UUID, post_ids: list[uuid.UUID]) -> None:
        if not post_ids:
            return
        key = self._key(user_id)
        at = self._clock()
        try:
            pipe = self._redis.pipeline()
            pipe.zadd(key, {str(p): at for p in post_ids})
            # Trim by age, then by count. Both, because either alone
            # leaves a way for the key to grow: a quiet user's key
            # would never hit the count cap, and a scripted one would
            # never hit the age cap.
            pipe.zremrangebyscore(key, "-inf", at - REMEMBER_SECONDS)
            pipe.zremrangebyrank(key, 0, -(MOST_REMEMBERED + 1))
            pipe.expire(key, REMEMBER_SECONDS)
            await pipe.execute()
        except Exception as caught:
            # Not recorded means it may be shown again. Acceptable.
            logger.warning("could not record impressions: %s", caught)

    async def forget(self, user_id: uuid.UUID) -> None:
        try:
            await self._redis.delete(self._key(user_id))
        except Exception as caught:
            # The lap simply does not reset. The filter relaxes
            # instead, which repeats pins - worse than a clean lap
            # and far better than an error on a scroll.
            logger.warning("could not reset the seen window: %s", caught)


def unseen(
    candidates: list[uuid.UUID], already: set[uuid.UUID]
) -> list[uuid.UUID]:
    """Candidates with the already-shown removed, order preserved."""
    return [c for c in candidates if c not in already]


__all__ = [
    "MOST_REMEMBERED",
    "REMEMBER_SECONDS",
    "InMemorySeen",
    "RedisSeen",
    "SeenStore",
    "unseen",
]

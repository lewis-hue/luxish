"""The seen-store the API actually uses, built once.

**One client for the process.** `redis.asyncio` pools connections
internally, so building a client per request creates a pool per
request and exhausts file descriptors under any real load - a failure
that only appears under concurrency, which is the worst kind to find
in production.

**A missing or broken Redis is not an error here.** The seen-filter
degrades to "nothing has been seen", so the feed repeats itself
rather than failing. That is the right trade for this particular
cache and the wrong one for a moderation gate, which is why the
decision is written down rather than inferred from the absence of a
`raise`.
"""

from __future__ import annotations

import logging

from app.domain.discovery.seen import RedisSeen, SeenStore

logger = logging.getLogger(__name__)

_store: SeenStore | None = None
_tried = False


def seen_store() -> SeenStore | None:
    """The shared seen-filter, or None if Redis could not be reached.

    None rather than an in-memory fallback, deliberately. `InMemorySeen`
    in a multi-process deployment is worse than nothing: each worker
    would believe a different set of pins had been shown, so a refresh
    served by another process repeats what the first one sent, and the
    bug looks like the filter is broken rather than absent.
    """
    global _store, _tried
    if _tried:
        return _store
    _tried = True
    try:
        from redis.asyncio import Redis

        from app.config import get_settings

        _store = RedisSeen(Redis.from_url(get_settings().redis_url))
        logger.info("seen-filter using redis")
    except Exception as caught:
        logger.warning("no seen-filter, the feed will repeat itself: %s", caught)
        _store = None
    return _store


def reset() -> None:
    """Drop the client. For tests."""
    global _store, _tried
    _store = None
    _tried = False


__all__ = ["reset", "seen_store"]

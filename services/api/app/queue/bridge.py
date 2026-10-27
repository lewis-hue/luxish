"""Running async code inside a Celery worker.

Celery has no native async support, and no official guidance for calling async
code from a task. That is a documented gap in the project, not an oversight we
can configure away — so this module is the bridge, and it is deliberately the
only place in the codebase that knows Celery and asyncio at the same time.

**The rule it exists to enforce: one event loop per worker process, alive for
the whole life of that process.** The obvious implementation — ``asyncio.run``
per task — is wrong here in a way that does not fail loudly. ``asyncio.run``
creates a loop, runs the coroutine, and *closes* the loop. An asyncpg pool
binds its connections to the loop that created them, so the second task either
finds a pool full of connections belonging to a closed loop, or silently opens
a fresh connection (with its TCP and TLS handshake) for every single job. The
first is a crash under load; the second is a slow service that looks correct.

So the loop is created once, in the ``worker_process_init`` signal, which
prefork fires **inside the child** — after the fork, which matters just as
much. A pool created in the parent and inherited through ``fork()`` hands the
same sockets to several processes at once and corrupts the connection stream.
Creating it post-fork is what makes the pool safe.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: The worker process's loop. Process-global on purpose: prefork gives each
#: child its own interpreter, so there is exactly one of these per process.
_loop: asyncio.AbstractEventLoop | None = None


class LoopNotStarted(RuntimeError):
    """A task tried to run a coroutine before the worker loop was installed.

    Almost always means the Celery app was imported without its signal
    handlers — see :func:`install`.
    """


def install() -> asyncio.AbstractEventLoop:
    """Create this process's event loop. Idempotent.

    Called from ``worker_process_init``. Returns the loop so a test can drive
    it directly instead of starting a worker.
    """
    global _loop
    if _loop is not None and not _loop.is_closed():
        return _loop

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    logger.info("worker event loop installed")
    return _loop


def shutdown() -> None:
    """Close this process's loop, cancelling whatever is still pending.

    Cancelling and then *draining* matters: a cancelled task gets to run its
    ``finally`` blocks, which is where a connection pool returns its sockets.
    Closing the loop without draining leaves them for the OS to reap and can
    strand server-side connections until they time out.
    """
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = None
        return

    pending = [task for task in asyncio.all_tasks(_loop) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        _loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

    _loop.run_until_complete(_loop.shutdown_asyncgens())
    _loop.close()
    _loop = None
    logger.info("worker event loop closed")


def current_loop() -> asyncio.AbstractEventLoop | None:
    """This process's loop, or None if one was never installed."""
    return None if _loop is None or _loop.is_closed() else _loop


def run(coro: Coroutine[Any, Any, T] | Awaitable[T]) -> T:
    """Run a coroutine to completion on this process's loop.

    This is the only sanctioned way for a Celery task to execute async code.
    It blocks the calling (worker) thread, which is correct: Celery's unit of
    concurrency is the process, and a task that returned before its work
    finished would be acknowledged early and the work lost.
    """
    loop = current_loop()
    if loop is None:
        raise LoopNotStarted(
            "no event loop in this process. The Celery app installs one from "
            "worker_process_init; a task running outside a worker must call "
            "bridge.install() first."
        )
    return loop.run_until_complete(coro)


__all__ = ["LoopNotStarted", "current_loop", "install", "run", "shutdown"]

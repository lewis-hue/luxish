"""Async job dispatch (ADR-018).

Celery and Redis provide dispatch and concurrency. PostgreSQL's ``jobs`` table
remains the record of what work exists, and :func:`app.queue.tasks.sweep` is
the re-drive authority. See :mod:`app.queue.celery_app` for why the broker is
deliberately not trusted with the truth.
"""

from __future__ import annotations


def install_dispatcher() -> None:
    """Point :mod:`app.domain.jobs` at Celery.

    Called explicitly by the API and worker entry points rather than on import,
    so that importing the domain never drags in a broker, and so the test suite
    runs with no dispatcher unless a test asks for one.
    """
    from app.domain.jobs import set_dispatcher
    from app.queue.tasks import dispatch

    set_dispatcher(lambda job_id, kind: dispatch(job_id, kind))


__all__ = ["install_dispatcher"]

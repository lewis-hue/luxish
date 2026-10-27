"""The Celery application (ADR-018).

Celery is the dispatch and concurrency layer. It is **not** the record of what
work exists: the ``jobs`` table is, and a sweeper re-enqueues anything Redis
loses. Four verified facts force that split, and each one is a way a job
disappears if you let the broker own the truth:

1. ``task_acks_late`` defaults to ``False``, so stock Celery acknowledges a
   message *before* running it. A worker killed mid-task loses the task with no
   trace. At-most-once, out of the box.
2. Redis is a Kombu *virtual* transport with emulated acks. In-flight messages
   are ordinary Redis keys, so durability is capped by the Redis persistence
   configuration, and managed Redis generally offers AOF or RDB, not both.
3. Recovery of abandoned messages runs *inside a worker*, on a timer. With no
   worker alive on a queue, Celery's own recovery path cannot run at all.
4. Cloud Run allows 10 non-configurable seconds between SIGTERM and SIGKILL.
   Celery's warm shutdown waits for running tasks, and our media and AI jobs
   take minutes, so a deploy would routinely kill work in flight.

The design that answers all four: **a Celery message carries nothing but a job
id.** The payload, the state, the attempt count and the idempotency key live in
Postgres. A lost message costs a wake-up, not work. A duplicated message is
harmless because :func:`~app.domain.jobs.claim_job_by_id` resolves the race in
a single locked statement, so exactly one worker proceeds and the other
declines. Idempotency is structural here rather than configured, which matters
because the broker cannot provide it.

Settings below depart from Celery's defaults wherever a default is wrong for
this shape. Each one says why, because a bare setting is indistinguishable from
a copied one.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from app.config import get_settings
from app.queue import bridge

logger = logging.getLogger(__name__)

#: Queue names, one per class of work, so a deployable can serve just one and
#: a slow queue cannot starve a fast one. A long media job must never delay a
#: stylist run the user is waiting on.
QUEUE_DEFAULT = "default"
QUEUE_MEDIA = "media"
QUEUE_AI = "ai"
QUEUE_MAINTENANCE = "maintenance"

QUEUES: tuple[str, ...] = (QUEUE_DEFAULT, QUEUE_MEDIA, QUEUE_AI, QUEUE_MAINTENANCE)

#: Job kind prefix to queue. A kind with no entry goes to the default queue.
QUEUE_BY_PREFIX: dict[str, str] = {
    "media.": QUEUE_MEDIA,
    "wardrobe.categorise": QUEUE_AI,
    "wardrobe.remove_background": QUEUE_MEDIA,
    "stylist.": QUEUE_AI,
}


def queue_for(kind: str) -> str:
    """Which queue a job kind belongs on."""
    for prefix, queue in QUEUE_BY_PREFIX.items():
        if kind.startswith(prefix):
            return queue
    return QUEUE_DEFAULT


def build_celery(settings=None) -> Celery:
    cfg = settings or get_settings()

    app = Celery("luxish", broker=cfg.celery_broker_url)

    app.conf.update(
        # -- what the broker is allowed to carry ---------------------------- #
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        # No result backend. Task results would be a second, weaker copy of
        # what the `jobs` table already holds authoritatively, and keeping two
        # answers to "did this run?" is how they come to disagree. Callers read
        # job state from Postgres.
        result_backend=None,
        task_ignore_result=True,
        #
        # -- the two settings that decide whether work survives ------------- #
        # Acknowledge only after the task returns. The default (False) is
        # at-most-once and silently loses a task whose worker dies.
        task_acks_late=True,
        # Reserve one message per process. With the default of 4, three
        # messages sit unacked with the visibility clock already running while
        # the first long job executes, so they can time out before they ever
        # start. Also keeps the blast radius of a SIGKILL to one job.
        worker_prefetch_multiplier=1,
        #
        # Deliberately NOT enabled: task_reject_on_worker_lost. Celery's own
        # documentation warns it can cause message loops, and on Redis a
        # rejected message is pushed back to the *head* of the queue, so a task
        # that reliably kills its worker is retried immediately and forever.
        # Postgres bounds retries with max_attempts instead, which Redis has no
        # equivalent of.
        #
        # -- shutdown ------------------------------------------------------- #
        # Cloud Run gives 10 seconds. This window is what lets a worker return
        # its unacked messages to the queue rather than leaving them stranded
        # until the visibility timeout expires, so it must stay comfortably
        # under the platform's limit.
        worker_soft_shutdown_timeout=cfg.celery_soft_shutdown_seconds,
        # Finish the current task if it can finish inside the window above.
        worker_enable_soft_shutdown_on_idle=True,
        #
        # -- transport ------------------------------------------------------ #
        broker_transport_options={
            # Set far longer than any task could run, so Redis never redelivers
            # and Postgres is the sole re-drive authority. Two independent
            # redelivery mechanisms racing is how one job becomes three.
            #
            # CAUTION: this value is per *consumer*, and the SHORTEST value
            # among every consumer on the broker wins. A tool connecting with
            # the Kombu default of 3600 (Flower, an exporter, a second service)
            # silently reimposes a one-hour timeout on our queues. Anything
            # that connects to this broker must set the same value.
            "visibility_timeout": cfg.celery_visibility_timeout_seconds,
            "global_keyprefix": f"{cfg.environment}:luxish:",
        },
        broker_connection_retry_on_startup=True,
        # A worker that cannot reach Redis should die and be restarted by the
        # platform rather than retry forever while reporting healthy.
        broker_connection_max_retries=10,
        #
        # -- routing -------------------------------------------------------- #
        task_default_queue=QUEUE_DEFAULT,
        task_queues=None,
        task_create_missing_queues=True,
        #
        # -- time limits ---------------------------------------------------- #
        # Hard limit kills the child process; the soft limit arrives first as a
        # catchable exception so a task can record why it is being stopped.
        task_soft_time_limit=cfg.celery_task_soft_time_limit_seconds,
        task_time_limit=cfg.celery_task_time_limit_seconds,
        #
        # -- observability -------------------------------------------------- #
        worker_send_task_events=True,
        task_send_sent_event=True,
        worker_hijack_root_logger=False,
        timezone="UTC",
        enable_utc=True,
    )

    # `imports` rather than `autodiscover_tasks`: autodiscover runs during this
    # call, and `app.queue.tasks` imports `celery_app` from this module, so the
    # import lands on a half-initialised module and fails. Listing the module
    # here defers the import to worker start-up, which is when the tasks are
    # actually needed.
    app.conf.imports = ("app.queue.tasks",)
    return app


celery_app = build_celery()


# --------------------------------------------------------------------------- #
# The async bridge, attached to the worker process lifecycle
# --------------------------------------------------------------------------- #
@worker_process_init.connect
def _install_event_loop(**_: object) -> None:
    """Create this child's event loop, after the fork.

    Post-fork is the point. A loop or a connection pool created in the parent
    and inherited through ``fork()`` hands the same sockets to several
    processes, which corrupts the connection stream rather than failing
    cleanly.
    """
    bridge.install()


@worker_process_shutdown.connect
def _close_event_loop(**_: object) -> None:
    bridge.shutdown()


__all__ = [
    "QUEUES",
    "QUEUE_AI",
    "QUEUE_DEFAULT",
    "QUEUE_MAINTENANCE",
    "QUEUE_MEDIA",
    "build_celery",
    "celery_app",
    "queue_for",
]

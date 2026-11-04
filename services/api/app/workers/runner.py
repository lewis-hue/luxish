"""Worker runner.

One deployable per queue class (ADR-003): the runner is given the kinds it
handles and a handler per kind, and does nothing else. A handler that raises
is a failure, which means backoff or dead-letter — never an infinite retry, and
never a silent swallow.

A handler raising :class:`~app.domain.jobs.AssetGone` is *not* a failure: the
work was correctly discarded because the asset was deleted, so the job
completes rather than retrying against something that no longer exists.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import CapabilityUnavailable
from app.domain.jobs import AssetGone, claim_job, complete_job, fail_job
from app.models.job import Job

if TYPE_CHECKING:  # pragma: no cover - imported for signatures only
    from app.providers.segmentation import SegmentationProvider
    from app.workers.categorise import GarmentClassifier, MediaStore

logger = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, Job], Awaitable[dict | None]]


class UnknownJobKind(LookupError):
    """A deployable was configured for a queue no handler serves."""

    def __init__(self, unknown: Sequence[str], known: Sequence[str]) -> None:
        self.unknown = tuple(unknown)
        self.known = tuple(known)
        super().__init__(
            f"no handler for job kind(s) {', '.join(unknown)}; "
            f"this service handles {', '.join(known)}"
        )


async def run_one(
    session: AsyncSession, *, handlers: dict[str, Handler], worker: str | None = None
) -> Job | None:
    """Claim and run at most one job. Returns the job, or None if idle."""
    job = await claim_job(session, kinds=list(handlers), worker=worker)
    if job is None:
        return None

    handler = handlers[job.kind]
    try:
        result = await handler(session, job)
    except AssetGone as exc:
        await complete_job(session, job, result={"discarded": exc.reason})
        logger.info(
            "job discarded by the write guard",
            extra={"job_id": str(job.id), "kind": job.kind, "reason": exc.reason},
        )
    except Exception as exc:  # noqa: BLE001 - the queue records every failure
        await fail_job(session, job, f"{type(exc).__name__}: {exc}")
        logger.warning(
            "job failed",
            extra={"job_id": str(job.id), "kind": job.kind, "state": job.state},
        )
    else:
        await complete_job(session, job, result=result)
    return job


async def run_forever(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    handlers: dict[str, Handler],
    worker: str | None = None,
    idle_sleep_seconds: float = 1.0,
    stop: asyncio.Event | None = None,
) -> None:
    """Poll for work until ``stop`` is set.

    One session per job so a failed job cannot poison the next one's
    transaction.
    """
    while not (stop and stop.is_set()):
        async with session_maker() as session:
            job = await run_one(session, handlers=handlers, worker=worker)
        if job is None:
            await asyncio.sleep(idle_sleep_seconds)


def media_handlers() -> dict[str, Handler]:
    """The media queue's handlers.

    ``media.derive`` has no computation step in Phase A — see
    ``app/workers/media.py``. It is registered so the queue, the guard and the
    dead-letter path are exercisable end to end.
    """
    from app.workers import media

    async def derive(session: AsyncSession, job: Job) -> dict | None:
        rows = await media.persist(session, job, derivatives=[])
        return {"derivatives": len(rows)}

    return {"media.derive": derive}


def stylist_handlers() -> dict[str, Handler]:
    """The stylist queue's handler.

    ``execute_run`` builds its own provider registry per job, because
    ``AIRunRecorder`` needs the job's session to record accounting rows in the
    same transaction as the outfit it is accounting for.
    """
    from app.domain import stylist

    return {stylist.JOB_KIND: stylist.handle_job}


def wardrobe_media_handlers(
    *,
    classifier: GarmentClassifier | None = None,
    segmenter: SegmentationProvider | None = None,
    store: MediaStore | None = None,
) -> dict[str, Handler]:
    """Categorisation and background removal.

    Every collaborator is injectable so the test suite can wire doubles, and
    every default *refuses* rather than fakes: with no credential configured
    the jobs fail with a recorded reason and the garment keeps its original
    photograph. A worker deployable passes the real three.

    The segmentation provider is chosen by name from
    :data:`~app.providers.segmentation.SEGMENTATION_PROVIDERS` so a swap is a
    config change rather than an edit here.
    """
    from app.config import get_settings
    from app.domain.garment_media import (
        BACKGROUND_REMOVAL_JOB_KIND,
        CATEGORISE_JOB_KIND,
    )
    from app.providers.base import AIRunRecorder
    from app.providers.meta import MetaProvider
    from app.providers.segmentation import SEGMENTATION_PROVIDERS
    from app.workers.categorise import MetaGarmentClassifier, categorise_handlers
    from app.workers.outfit import (
        DETECT_OUTFIT_JOB_KIND,
        SPLIT_SHOTS_JOB_KIND,
        MetaOutfitDetector,
        detect_outfit,
        split_shots,
    )
    from app.workers.account_export import EXPORT_JOB_KIND
    from app.workers.packshot import PACKSHOT_JOB_KIND
    from app.workers.piece_packshot import PIECE_PACKSHOT_JOB_KIND
    from app.workers.post_vision import VISION_JOB_KIND
    from app.workers.post_shape import SHAPE_JOB_KIND
    from app.workers.render import MetaGarmentRenderer

    cfg = get_settings()
    if store is None:
        store = build_media_store(cfg)

    # Injected collaborators are used as given; that is the test path.
    if classifier is not None and segmenter is not None:
        return categorise_handlers(
            classifier=classifier, segmenter=segmenter, store=store
        )

    # Otherwise the providers are built **per job**, not once here, because
    # each needs an AIRunRecorder bound to that job's session. The providers
    # refuse to run without one, and they are right to: an unaccounted model
    # call is spend nobody can attribute to a user or a feature. Building them
    # at start-up would mean either no recorder or a recorder holding a
    # session that has long since closed.
    def _bound(session: AsyncSession) -> dict[str, Handler]:
        recorder = AIRunRecorder(session)
        return categorise_handlers(
            classifier=classifier or MetaGarmentClassifier(
                MetaProvider(recorder=recorder)
            ),
            segmenter=segmenter
            or SEGMENTATION_PROVIDERS[cfg.segmentation_provider](recorder=recorder),
            store=store,
        )

    async def _categorise(session: AsyncSession, job: Job) -> dict | None:
        return await _bound(session)[CATEGORISE_JOB_KIND](session, job)

    async def _remove_background(session: AsyncSession, job: Job) -> dict | None:
        return await _bound(session)[BACKGROUND_REMOVAL_JOB_KIND](session, job)

    async def _detect_outfit(session: AsyncSession, job: Job) -> dict | None:
        # Same per-job provider construction, same reason: the detector makes
        # a paid call and needs a recorder bound to this job's session. The
        # renderer shares the provider because it is the same billed account
        # and the same run ledger; it is only reached for a garment the
        # photograph hides, so most jobs never call it.
        recorder = AIRunRecorder(session)
        provider = MetaProvider(recorder=recorder)
        return await detect_outfit(
            session,
            job,
            detector=MetaOutfitDetector(provider),
            segmenter=segmenter
            or SEGMENTATION_PROVIDERS[cfg.segmentation_provider](recorder=recorder),
            store=store,
            renderer=MetaGarmentRenderer(provider),
        )

    async def _split_shots(session: AsyncSession, job: Job) -> dict | None:
        # The same detector and segmenter the intake split uses, for
        # the same reason: finding the garments in a photograph is one
        # problem however it was asked for. What differs is what is
        # done with them - wardrobe rows there, studio shots here.
        recorder = AIRunRecorder(session)
        provider = MetaProvider(recorder=recorder)
        return await split_shots(
            session,
            job,
            detector=MetaOutfitDetector(provider),
            segmenter=segmenter
            or SEGMENTATION_PROVIDERS[cfg.segmentation_provider](recorder=recorder),
            store=store,
        )

    async def _read_post(session: AsyncSession, job: Job) -> dict | None:
        # One cheap vision call per pin, once. This is what stops a
        # mislabelled photograph being ranked by its label: the
        # subject comes from the picture, and an author cannot write
        # it.
        from app.workers.post_vision import MetaPostVisionReader, read_post_vision

        provider = MetaProvider(recorder=AIRunRecorder(session))
        return await read_post_vision(
            session, job, reader=MetaPostVisionReader(provider), store=store
        )

    async def _build_export(session: AsyncSession, job: Job) -> dict | None:
        # Reads rows and object storage, writes one zip. No provider
        # and no credential check: there is no model call anywhere in
        # an export, which is why it sits on the media queue rather
        # than behind the paid work.
        from app.workers.account_export import build_export

        return await build_export(session, job, store=store)

    async def _shape_post(session: AsyncSession, job: Job) -> dict | None:
        # Pixels only - a rotate and a pad - so no provider and no
        # credential check. A fit whose picture already fits is left
        # alone, which is almost all of them.
        from app.workers.post_shape import shape_post_cover

        return await shape_post_cover(session, job, store=store)

    async def _generate_avatar(session: AsyncSession, job: Job) -> dict | None:
        from app.workers.avatar import MetaAvatarRenderer
        from app.workers.avatar_jobs import generate_avatar_job

        provider = MetaProvider(recorder=AIRunRecorder(session))
        return await generate_avatar_job(
            session, job, renderer=MetaAvatarRenderer(provider), store=store
        )

    async def _try_on(session: AsyncSession, job: Job) -> dict | None:
        from app.workers.avatar import MetaAvatarRenderer
        from app.workers.avatar_jobs import try_on_job
        from app.workers.fit_vision import MetaFitReader

        provider = MetaProvider(recorder=AIRunRecorder(session))
        return await try_on_job(
            session,
            job,
            renderer=MetaAvatarRenderer(provider),
            store=store,
            # Only used when the render came from somebody else's fit that
            # nobody has read yet. The curated-look path never touches it.
            reader=MetaFitReader(provider),
        )

    async def _likeness(session: AsyncSession, job: Job) -> dict | None:
        from app.workers.avatar import MetaAvatarRenderer
        from app.workers.avatar_jobs import likeness_job

        provider = MetaProvider(recorder=AIRunRecorder(session))
        return await likeness_job(
            session, job, renderer=MetaAvatarRenderer(provider), store=store
        )

    async def _screen_bio(session: AsyncSession, job: Job) -> dict | None:
        from app.workers.screen import (  # noqa: E402
            BIO_SCREEN_JOB_KIND,
            MetaPostScreener,
            bio_screen_handlers,
        )

        # Same fail-closed construction as the post screen: no
        # credential means no screener, and the handler holds the bio
        # rather than approving it blind.
        screener = None
        if cfg.meta_api_key:
            screener = MetaPostScreener(MetaProvider(recorder=AIRunRecorder(session)))
        handlers = bio_screen_handlers(screener=screener)
        return await handlers[BIO_SCREEN_JOB_KIND](session, job)

    async def _take_shot(session: AsyncSession, job: Job) -> dict | None:
        from app.workers.garment_studio import MetaGarmentStudio
        from app.workers.garment_studio_jobs import take_shot_job

        provider = MetaProvider(recorder=AIRunRecorder(session))
        return await take_shot_job(
            session,
            job,
            studio=MetaGarmentStudio(provider),
            store=store,
        )

    async def _visual_search(session: AsyncSession, job: Job) -> dict | None:
        """Read a picture somebody wants to search with."""
        from app.workers.fit_vision import MetaFitReader
        from app.workers.visual_search_jobs import visual_search_job

        if not cfg.meta_api_key:
            raise CapabilityUnavailable(
                "No model credential is configured, so a picture cannot be read.",
                detail={"capability": "visual_search"},
            )
        reader = MetaFitReader(MetaProvider(recorder=AIRunRecorder(session)))
        return await visual_search_job(session, job, reader=reader, store=store)

    async def _screen_banner(session: AsyncSession, job: Job) -> dict | None:
        """Screen one profile banner, on the image screen.

        Fail-closed like every other screen here: no credential means
        no screener, and the banner is held rather than shown blind.
        """
        from app.workers.screen import (  # noqa: E402
            BANNER_SCREEN_JOB_KIND,
            MetaPostScreener,
            banner_screen_handlers,
        )

        screener = None
        if cfg.meta_api_key:
            screener = MetaPostScreener(
                MetaProvider(recorder=AIRunRecorder(session))
            )
        handlers = banner_screen_handlers(screener=screener, store=store)
        return await handlers[BANNER_SCREEN_JOB_KIND](session, job)

    async def _screen_comment(session: AsyncSession, job: Job) -> dict | None:
        """Screen one comment.

        Same fail-closed construction as the post and bio screens: no
        credential means no screener, and the handler holds the comment
        rather than publishing it blind.
        """
        from app.workers.screen import (
            COMMENT_SCREEN_JOB_KIND,
            MetaPostScreener,
            comment_screen_handlers,
        )

        screener = None
        if cfg.meta_api_key:
            screener = MetaPostScreener(
                MetaProvider(recorder=AIRunRecorder(session))
            )
        handlers = comment_screen_handlers(screener=screener)
        return await handlers[COMMENT_SCREEN_JOB_KIND](session, job)

    async def _describe_fit(session: AsyncSession, job: Job) -> dict | None:
        """Read the clothes out of a posted photograph.

        Fail-closed in the same shape as the screeners: no credential
        means no reader, and the job refuses rather than writing an empty
        description that would then be served as a caption.
        """
        from app.workers.fit_vision_jobs import describe_fit_job

        if not cfg.meta_api_key:
            raise CapabilityUnavailable(
                "No model credential is configured, so a fit cannot be read.",
                detail={"capability": "fit_description"},
            )
        from app.workers.fit_vision import MetaFitReader

        recorder = AIRunRecorder(session)
        reader = MetaFitReader(MetaProvider(recorder=recorder))
        return await describe_fit_job(
            session,
            job,
            reader=reader,
            store=store,
            # The same segmenter the wardrobe cuts garments with. It
            # cuts each described piece out of the photograph so the
            # stylised figure can wear the real thing rather than a
            # redrawing of it, and is optional here: without one the
            # fit is still described, captioned and tryable.
            segmenter=segmenter
            or SEGMENTATION_PROVIDERS[cfg.segmentation_provider](recorder=recorder),
        )

    async def _screen_post(session: AsyncSession, job: Job) -> dict | None:
        from app.workers.screen import (
            MetaPostScreener,
            SCREEN_JOB_KIND,
            screen_handlers,
        )

        # Built per job for the same recorder reason as everything above.
        # No credential means no screener, and the handler holds the post
        # rather than approving blind: the gate fails closed.
        screener = None
        if cfg.meta_api_key:
            screener = MetaPostScreener(
                MetaProvider(recorder=AIRunRecorder(session))
            )
        handlers = screen_handlers(screener=screener, store=store)
        return await handlers[SCREEN_JOB_KIND](session, job)

    async def _make_packshot(session: AsyncSession, job: Job) -> dict | None:
        # One image edit per garment added to a wardrobe, once.
        #
        # The same studio the Studio tab uses, running its `packshot`
        # treatment: a garment photographed on a bed cuts out as the
        # same crumpled garment with the room removed, and this
        # re-stages it the way a shop photographs stock. It is an edit
        # of the owner's own photograph, so it is still their garment.
        #
        # Last in the pipeline and failure-tolerant: if it cannot run,
        # the cut-out stands and the wardrobe is unchanged.
        from app.workers.garment_studio import MetaGarmentStudio
        from app.workers.packshot import make_packshot

        return await make_packshot(
            session,
            job,
            studio=MetaGarmentStudio(
                MetaProvider(recorder=AIRunRecorder(session))
            ),
            store=store,
        )

    async def _draw_piece(session: AsyncSession, job: Job) -> dict | None:
        # A garment nobody here owns, drawn from the words the
        # stylist used to name it - so a reply that says "you'd need
        # white sneakers" can show them rather than only say it.
        #
        # One drawing per phrase for the whole product: the row is
        # keyed on the words and shared by every account, which is
        # what makes this cost a fraction of the per-person render it
        # replaced.
        from app.workers.piece_packshot import PieceArtist, draw_piece

        return await draw_piece(
            session,
            job,
            artist=PieceArtist(MetaProvider(recorder=AIRunRecorder(session))),
            store=store,
        )

    from app.domain.posts import SCREEN_JOB_KIND as POST_SCREEN_JOB_KIND

    return {
        CATEGORISE_JOB_KIND: _categorise,
        BACKGROUND_REMOVAL_JOB_KIND: _remove_background,
        PACKSHOT_JOB_KIND: _make_packshot,
        PIECE_PACKSHOT_JOB_KIND: _draw_piece,
        DETECT_OUTFIT_JOB_KIND: _detect_outfit,
        SPLIT_SHOTS_JOB_KIND: _split_shots,
        SHAPE_JOB_KIND: _shape_post,
        EXPORT_JOB_KIND: _build_export,
        VISION_JOB_KIND: _read_post,
        GENERATE_JOB_KIND: _generate_avatar,
        TRY_ON_JOB_KIND: _try_on,
        LIKENESS_JOB_KIND: _likeness,
        SHOT_JOB_KIND: _take_shot,
        DESCRIBE_JOB_KIND: _describe_fit,
        COMMENT_SCREEN_JOB_KIND: _screen_comment,
        BANNER_SCREEN_JOB_KIND: _screen_banner,
        VISUAL_SEARCH_JOB_KIND: _visual_search,
        POST_SCREEN_JOB_KIND: _screen_post,
        BIO_SCREEN_JOB_KIND: _screen_bio,
    }


def build_media_store(cfg: Any) -> MediaStore:
    """The store the configured upload mode implies.

    Tied to `upload_storage_mode` rather than configured separately, because
    the two cannot disagree: a worker reading from a different place than the
    client wrote to would find nothing, and would report it as a missing
    object rather than as the misconfiguration it is.

    `gcs_signed_url` gets the refusing store, which is the safe answer for a
    mode that is not implemented: it fails loudly instead of returning empty
    bytes that would be composited into a blank cut-out and saved as though
    it had worked.

    `simulated` gets the in-memory store, which is what declares
    ``storage_mode = "simulated"``. Mapping the mode to the *refusing* store
    was a real defect and the symptom was specific: with no explicit mode
    configured the default is `simulated`, so avatar generation failed with
    "no object-storage credential configured" on a machine that had no
    credential to configure and did not need one. The in-memory store is
    process-local — a worker's cut-out is invisible to the API that serves it
    — so it is correct only for a single-process build, and both of its reads
    raise rather than returning nothing when a key is absent.
    """
    from app.workers.categorise import UnavailableMediaStore

    if cfg.upload_storage_mode == "local_file":
        from app.storage.local import build_local_store

        return build_local_store(
            environment=cfg.environment, root=cfg.local_media_root
        )
    if cfg.upload_storage_mode == "simulated":
        return _simulated_store()
    return UnavailableMediaStore()


#: The one in-memory store this process uses.
#:
#: A singleton, and it has to be. `build_media_store` is called per request,
#: so a fresh `InMemoryMediaStore()` each time would accept a write and then
#: fail every subsequent read — a *silent* success followed by a confusing
#: failure, which is strictly worse than the loud refusal it replaced.
_SIMULATED: Any | None = None


def _simulated_store() -> Any:
    global _SIMULATED
    if _SIMULATED is None:
        from app.workers.categorise import InMemoryMediaStore

        _SIMULATED = InMemoryMediaStore()
    return _SIMULATED


# **Imported here rather than at the top, deliberately.** Each of
# these modules imports from this one, so hoisting them would close
# an import cycle and fail at start-up. A linter cannot tell a
# cycle-break from carelessness, so it is told.
from app.domain.avatar_renders import (  # noqa: E402
    GENERATE_JOB_KIND,
    LIKENESS_JOB_KIND,
    TRY_ON_JOB_KIND,
)
from app.domain.fit_descriptions import DESCRIBE_JOB_KIND  # noqa: E402
from app.domain.garment_studio import SHOT_JOB_KIND  # noqa: E402
from app.domain.visual_search import VISUAL_SEARCH_JOB_KIND  # noqa: E402
from app.workers.screen import (  # noqa: E402
    BANNER_SCREEN_JOB_KIND,
    BIO_SCREEN_JOB_KIND,
    COMMENT_SCREEN_JOB_KIND,
)


def all_handlers(
    kinds: Sequence[str] | None = None,
    *,
    classifier: GarmentClassifier | None = None,
    segmenter: SegmentationProvider | None = None,
    store: MediaStore | None = None,
) -> dict[str, Handler]:
    """Every handler this service knows how to run.

    ``kinds`` selects a subset, which is how one deployable per queue class is
    achieved from a single image (ADR-003). An unknown kind is *not* silently
    dropped: a deployable asked to serve a queue nobody handles would poll
    forever and look healthy, so it raises instead.
    """
    from app.workers.push import push_handlers

    handlers = {
        **media_handlers(),
        **stylist_handlers(),
        **wardrobe_media_handlers(
            classifier=classifier, segmenter=segmenter, store=store
        ),
        # The outbox drain. Its usual trigger is the beat schedule
        # (`luxish.deliver_push`), so this registration is what makes
        # the same work enqueueable as a job - which matters because
        # the kind existed, was exported, and was claimed by nobody:
        # `all_handlers` refuses an unhandled kind loudly, and this
        # one slipped through by never being asked for.
        **push_handlers(),
    }
    if kinds is None:
        return handlers

    unknown = sorted(set(kinds) - set(handlers))
    if unknown:
        raise UnknownJobKind(unknown, sorted(handlers))
    return {kind: handlers[kind] for kind in kinds}

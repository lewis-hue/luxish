"""Application factory (ADR-003: one deployable, per-domain routers)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.middleware import RequestIdMiddleware, configure_logging

API_PREFIX = "/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Point `enqueue` at Celery. Without this the whole queue is
        # write-only: a job row lands in Postgres, `_notify` finds no
        # dispatcher and returns, and no worker is ever told the work exists.
        # The sweeper would eventually find it, but "eventually" is a user
        # watching a spinner, so the dispatch is the fast path and the sweeper
        # is the safety net.
        #
        # Here rather than at import time, so that importing the domain never
        # drags in a broker and the test suite runs without one: an ASGI
        # transport does not run lifespan events.
        try:
            from app.queue import install_dispatcher

            install_dispatcher()
        except Exception:  # dispatch is latency, not loss
            # A broker that cannot be reached must not stop the API serving.
            # Jobs still commit, and the sweeper re-drives them.
            logging.getLogger(__name__).warning(
                "job dispatch unavailable; the sweeper will re-drive queued work",
                exc_info=True,
            )

        yield
        from app.db.session import dispose_engine

        try:
            await dispose_engine()
        except Exception:  # noqa: BLE001, S110 - shutdown must not raise
            # Nothing useful can be done if the pool is already gone, and a
            # raise here would mask the real reason the process is stopping.
            pass

    app = FastAPI(
        title="LUXish API",
        version="0.1.0",
        description="Wardrobe, stylist, shopping and community backend.",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        """Liveness. Deliberately touches no dependency."""
        return {"status": "ok", "environment": cfg.environment}

    _install_routers(app)
    return app


def _install_routers(app: FastAPI) -> None:
    from app.routers import (
        account_export,
        auth,
        avatar,
        billing,
        brand_studio,
        community,
        collections,
        consents,
        feed,
        garment_studio,
        messages,
        moodboards,
        notifications,
        planner,
        posts,
        profile,
        profiles,
        push,
        regional,
        shopping,
        shops,
        social_import,
        speech,
        studio,
        stylist,
        taste,
        uploads,
        wardrobe,
        wardrobe_media,
    )

    # `wardrobe_media` shares the /wardrobe prefix with `wardrobe`. Their path
    # spaces are disjoint, so registration order cannot change which handler a
    # request reaches — a test asserts that, rather than trusting the ordering.
    for module in (
        account_export,
        auth,
        avatar,
        billing,
        brand_studio,
        community,
        collections,
        consents,
        feed,
        garment_studio,
        messages,
        moodboards,
        notifications,
        planner,
        posts,
        profile,
        profiles,
        push,
        shopping,
        shops,
        speech,
        uploads,
        wardrobe,
        wardrobe_media,
        social_import,
        regional,
        studio,
        stylist,
        taste,
    ):
        app.include_router(module.router, prefix=API_PREFIX)
    # DELETE /v1/account sits outside the /auth prefix.
    app.include_router(auth.account_router, prefix=API_PREFIX)


app = create_app()

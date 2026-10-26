"""Application factory (ADR-003: one deployable, per-domain routers)."""

from __future__ import annotations

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
        yield
        from app.db.session import dispose_engine

        try:
            await dispose_engine()
        except Exception:  # pragma: no cover - shutdown is best effort
            pass

    app = FastAPI(
        title="Atelier API",
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
    from app.routers import auth, social_import, uploads, wardrobe

    for module in (auth, uploads, wardrobe, social_import):
        app.include_router(module.router, prefix=API_PREFIX)
    # DELETE /v1/account sits outside the /auth prefix.
    app.include_router(auth.account_router, prefix=API_PREFIX)


app = create_app()

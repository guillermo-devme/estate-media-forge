"""FastAPI application factory.

Wires structured logging, the /media static mount, shared resources (job store,
usage ledger, ARQ pool, Wix refund client) on app.state, the routers, and a
global exception handler that returns structured JSON (never a stack trace).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.jobs.enqueue import close_arq_pool, enqueue_job, get_arq_pool
from app.jobs.store import JobStore
from app.obs.logging import configure_logging, get_logger
from app.providers.wix_client import WixRefundClient
from app.routers import health, jobs, media_kit, upscale, video
from app.wallet.repository import UsageRepository

_logger = get_logger("app.main")

_DESCRIPTION = (
    "Server-to-server compute backend for the real-estate media-kit platform. "
    "Turns a property photo into a 3-aspect-ratio media kit (upscale -> expand -> "
    "cinematic image-to-video) via fal.ai. Called only by the Wix Velo backend over "
    "HMAC-signed requests. Owns no balance; responses speak credits, never USD."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    usage = UsageRepository()
    await usage.create_all()
    app.state.usage = usage
    app.state.job_store = JobStore()
    app.state.refund_client = WixRefundClient()
    app.state.arq_pool = await get_arq_pool()
    app.state.enqueue = enqueue_job

    _logger.info("app.startup")
    try:
        yield
    finally:
        await usage.dispose()
        await app.state.job_store.aclose()
        await close_arq_pool()
        _logger.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Real-Estate Media-Kit API",
        description=_DESCRIPTION,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Static media (generated assets are served from here).
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    app.include_router(health.router)
    app.include_router(media_kit.router)
    app.include_router(upscale.router)
    app.include_router(video.router)
    app.include_router(jobs.router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Structured error; details logged server-side, never leaked to clients.
        _logger.error(
            "unhandled_exception",
            extra={"path": request.url.path, "method": request.method, "error": repr(exc)},
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    return app


app = create_app()

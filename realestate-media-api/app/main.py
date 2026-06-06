"""FastAPI application factory.

Wires structured logging, the /media static mount, shared resources (job store,
usage ledger, ARQ pool, Wix refund client) on app.state, the routers, a global
exception handler (structured JSON, never a stack trace), and a polished OpenAPI
schema documenting the HMAC service-auth headers and the Wix-fronted lifecycle.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.jobs.enqueue import close_arq_pool, enqueue_job, get_arq_pool
from app.jobs.store import JobStore
from app.obs.logging import configure_logging, get_logger
from app.providers.wix_client import WixRefundClient
from app.routers import health, jobs, media_kit, metrics, quotation, upscale, video
from app.wallet.repository import UsageRepository

_logger = get_logger("app.main")

_SUMMARY = "Async fal.ai media-kit compute backend, fronted by Wix (auth + balance)."

_DESCRIPTION = """\
Server-to-server compute backend for the **real-estate media-kit** platform. A property photo
becomes a 3-aspect-ratio media kit (1:1, 9:16, 16:9) through **upscale → expand/outpaint →
cinematic image-to-video**, powered by [fal.ai](https://fal.ai) and orchestrated with LangGraph.

### Credits model
Responses speak **credits only** — USD and internal provider cost **never leave the server**.
Pricing math (`provider_cost × earnings_ratio ÷ credit_peg`) lives entirely in this service.

### Who owns what
This API owns **no balance**. The **Wix Studio (Velo)** site owns member auth, roles, and the
**token balance of record** (Wix CMS). Wix is the only caller, over **HMAC-signed** requests.
Stripe (via a Wix webhook) is the only path that adds tokens.

### Lifecycle (Wix-fronted)
```
 Wix quote ─▶ Wix decrement (the hold) ─▶ submit(member_id, client_ref, quoted_credits) ─▶ 202
        ─▶ poll GET /v1/jobs/{id} ─▶ completed
                                   └─ partial/failed ─▶ worker refunds failed ratios → Wix
```

### Auth
Every `/v1` endpoint (except readiness) requires the HMAC service headers shown in **Authorize**:
`X-Service-Key`, `X-Member-Id`, `X-Timestamp`, `X-Nonce`, `X-Signature`
(signature over `{ts}.{nonce}.{member_id}.{sha256(body)}`). A member may act only on their own
`member_id`; cross-member reads return 404.
"""

_HOW_IT_WORKS = """\

---
**How quotation + polling works (Wix fronts auth + balance)**

1. Wix calls `POST /v1/quotation` to price a service in credits, compares it to the member's CMS
   balance, and decrements the wallet (the hold).
2. Wix calls a submit endpoint with `member_id`, `client_ref`, and `quoted_credits`; we verify the
   HMAC, record usage, create the job exactly-once per `client_ref`, enqueue, and return `202`.
3. Wix polls `GET /v1/jobs/{job_id}` until the job is `completed`, `partial`, or `failed`.
4. On partial/total failure the worker refunds exactly the failed ratios' credits back to Wix
   (idempotent on `refund_{job_id}`).
"""

_OPENAPI_TAGS = [
    {"name": "quotation", "description": "Pure pricing — credits + per-stage breakdown."},
    {"name": "pricing", "description": "Allowance: how many of each service a balance buys."},
    {
        "name": "media-kit",
        "description": "Submit a full 3-ratio media kit (upscale → expand → i2v).",
    },
    {"name": "upscale", "description": "Submit a standalone upscale job."},
    {"name": "video", "description": "Submit a standalone image-to-video job."},
    {"name": "jobs", "description": "Poll job status (ownership-enforced) + client_ref lookup."},
    {"name": "metrics", "description": "Lightweight operational counters."},
    {"name": "health", "description": "Liveness + readiness probes (no auth)."},
]

# ApiKey-style security schemes over the HMAC headers (real check = prompt 06 dependency).
_HMAC_SECURITY_SCHEMES = {
    "ServiceKey": {"type": "apiKey", "in": "header", "name": "X-Service-Key"},
    "MemberId": {"type": "apiKey", "in": "header", "name": "X-Member-Id"},
    "Timestamp": {"type": "apiKey", "in": "header", "name": "X-Timestamp"},
    "Nonce": {"type": "apiKey", "in": "header", "name": "X-Nonce"},
    "Signature": {"type": "apiKey", "in": "header", "name": "X-Signature"},
}

# Endpoints reachable without the HMAC headers.
_OPEN_PATHS = {"/health", "/v1/ready"}


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


def _build_openapi(app: FastAPI):
    """Custom OpenAPI: HMAC security scheme + a 'how it works' section."""

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            summary=_SUMMARY,
            description=_DESCRIPTION + _HOW_IT_WORKS,
            routes=app.routes,
            tags=_OPENAPI_TAGS,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {}).update(
            _HMAC_SECURITY_SCHEMES
        )
        # Apply the HMAC headers to every protected operation (all but the open paths).
        requirement = [{name: [] for name in _HMAC_SECURITY_SCHEMES}]
        for path, operations in schema.get("paths", {}).items():
            if path in _OPEN_PATHS:
                continue
            for operation in operations.values():
                if isinstance(operation, dict):
                    operation["security"] = requirement
        app.openapi_schema = schema
        return schema

    return custom_openapi


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Real-Estate Media-Kit API",
        summary=_SUMMARY,
        description=_DESCRIPTION,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=_OPENAPI_TAGS,
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
    app.include_router(quotation.router)
    app.include_router(metrics.router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Structured error; details logged server-side, never leaked to clients.
        _logger.error(
            "unhandled_exception",
            extra={"path": request.url.path, "method": request.method, "error": repr(exc)},
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    app.openapi = _build_openapi(app)
    return app


app = create_app()

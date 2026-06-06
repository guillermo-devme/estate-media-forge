"""Standalone upscale submit endpoint (same client_ref idempotency)."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import Auth
from app.routers._shared import EnqueueDep, QueueDepthDep, StoreDep, UsageDep, submit_job
from app.schemas.enums import ServiceType
from app.schemas.requests import UpscaleRequest
from app.schemas.responses import JobAccepted

router = APIRouter(prefix="/v1", tags=["upscale"])


@router.post(
    "/upscale",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an upscale job",
    description="""Upscale a property image across one or more aspect ratios. Returns 202 immediately.

**Purpose:** A lighter, cheaper alternative to the full media kit when the member only needs a
high-res image (no video). Uses fal.ai Clarity Upscaler.

**Use case — quick listing photo enhancement:**

1. Agent has a low-res photo → member clicks "Enhance".
2. Velo: `getQuote('upscale')` → `spend` → `callFastApi('/v1/upscale')`.
3. This endpoint: validate → record usage → create job → enqueue → **202**.
4. Poll until `completed` → each requested ratio has an `upscaled_url`.

```
 Wix Velo                    FastAPI /v1/upscale
 ────────                    ──────────────────
 spend(clientRef) ──────────▶ HMAC verify → create job → enqueue
 ◀──── 202 {job_id}           Worker: upscale per ratio → save
 poll ──────────────────────▶ status + upscaled_url[]
```

Same idempotency and backpressure guarantees as `/v1/media-kit`.
""",
)
async def submit_upscale(
    req: UpscaleRequest,
    auth: Auth,
    store: StoreDep,
    usage: UsageDep,
    enqueue: EnqueueDep,
    queue_depth: QueueDepthDep,
) -> JobAccepted:
    return await submit_job(
        service=ServiceType.UPSCALE,
        req=req,
        auth=auth,
        store=store,
        usage=usage,
        enqueue=enqueue,
        queue_depth=queue_depth,
    )

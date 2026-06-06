"""Media-kit submit endpoint.

Submit flow (fast path — no fal, no balance logic in the request thread)

POST /v1/media-kit    (Auth = verify_service_request)
       | body: { ...params, member_id, client_ref, quoted_credits }
       v
idempotency: get_job_by_client_ref -> if exists, return SAME job_id (no re-create)
       v
usage.record_event(submitted) -> create_job_idempotent (SETNX) -> enqueue process_media_job
       v
202 JobAccepted { job_id, status:queued, poll_url, quoted_credits }
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import Auth
from app.routers._shared import EnqueueDep, QueueDepthDep, StoreDep, UsageDep, submit_job
from app.schemas.enums import ServiceType
from app.schemas.requests import MediaKitRequest
from app.schemas.responses import JobAccepted

router = APIRouter(prefix="/v1", tags=["media-kit"])


@router.post(
    "/media-kit",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a media-kit job",
    description="""Fan out a property photo into a 3-ratio media kit (1:1, 9:16, 16:9) through
**upscale → expand/outpaint → cinematic image-to-video**. Returns 202 immediately — all heavy
fal.ai work runs in a background worker.

**Purpose:** This is the primary spend endpoint. Wix has already quoted, role-checked, and
decremented the member's balance. We verify the HMAC, record usage, create the job, enqueue it,
and return a `job_id` + `poll_url` for status tracking.

**Use case — generating a listing media kit:**

1. Agent uploads a property photo → member clicks "Generate Media Kit".
2. Velo web method: `assertRole` → `getQuote` → `spend(clientRef)` → `callFastApi('/v1/media-kit')`.
3. **This endpoint**: validates → records usage → creates job (idempotent on `client_ref`) → enqueues → **202**.
4. Member polls `GET /v1/jobs/{job_id}` until `completed` (3 ratios with video URLs).

```
 Wix Velo                    FastAPI /v1/media-kit              Worker (ARQ)
 ────────                    ─────────────────────              ────────────
 spend(clientRef) ──────────▶ verify HMAC
                              idempotent? (SETNX clientref)
                              record usage(submitted)
                              create job (queued, 3 ratios)
                              enqueue → ARQ ─────────────────────▶ fan-out 3 ratios
 ◀──── 202 {job_id, poll_url}                                     │ upscale → expand → i2v
                                                                   │ per ratio
 poll GET /v1/jobs/{id} ─────▶ status + assets ◀─────────────────── update per ratio
 ◀──── completed + video_url[]                                     settle (refund if partial)
```

**Idempotency:** Two submits with the same `client_ref` (e.g. a Wix retry after a timeout) return
the **same `job_id`** and create only one job/enqueue. The nonce check (prompt 06) separately
rejects byte-identical replays; `client_ref` is the complementary guard for legitimate retries
with a fresh timestamp/nonce.

**Backpressure:** If the queue is at `MAX_QUEUE_DEPTH`, returns **429 + Retry-After** (no job
created, no credits consumed — Wix should wait and retry).
""",
)
async def submit_media_kit(
    req: MediaKitRequest,
    auth: Auth,
    store: StoreDep,
    usage: UsageDep,
    enqueue: EnqueueDep,
    queue_depth: QueueDepthDep,
) -> JobAccepted:
    return await submit_job(
        service=ServiceType.MEDIA_KIT,
        req=req,
        auth=auth,
        store=store,
        usage=usage,
        enqueue=enqueue,
        queue_depth=queue_depth,
    )

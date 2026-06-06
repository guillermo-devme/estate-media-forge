"""Standalone image-to-video submit endpoint (same client_ref idempotency)."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import Auth
from app.routers._shared import EnqueueDep, QueueDepthDep, StoreDep, UsageDep, submit_job
from app.schemas.enums import ServiceType
from app.schemas.requests import ImageToVideoRequest
from app.schemas.responses import JobAccepted

router = APIRouter(prefix="/v1", tags=["image-to-video"])


@router.post(
    "/image-to-video",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an image-to-video job",
    description="""Generate a cinematic walkthrough clip from a property image, per requested aspect ratio.
Returns 202 immediately.

**Purpose:** Standalone video generation (no upscale/expand) for members who already have a
high-quality still. Uses fal.ai Seedance 2.0 with a cinematic prompt.

**Use case — social media video from a hero shot:**

1. Member has a polished kitchen photo → wants a 9:16 reel.
2. Velo: `getQuote('image_to_video', { duration_seconds: 8 })` → `spend` → `callFastApi`.
3. This endpoint: validate → record usage → create job → enqueue → **202**.
4. Poll until `completed` → each ratio has a `video_url` (cinematic walkthrough).

```
 Wix Velo                    FastAPI /v1/image-to-video
 ────────                    ──────────────────────────
 spend(clientRef) ──────────▶ HMAC verify → create job → enqueue
 ◀──── 202 {job_id}           Worker: i2v per ratio (prompt + duration) → save
 poll ──────────────────────▶ status + video_url[]
```

The default cinematic prompt fills `room_name`:
> "Create a 3d walkthrough animation of this property room: {room_name}. Add soft, clean elegant
> lighting and smooth camera movements..."

Override with `prompt_override` if needed. Same idempotency and backpressure guarantees.
""",
)
async def submit_image_to_video(
    req: ImageToVideoRequest,
    auth: Auth,
    store: StoreDep,
    usage: UsageDep,
    enqueue: EnqueueDep,
    queue_depth: QueueDepthDep,
) -> JobAccepted:
    return await submit_job(
        service=ServiceType.IMAGE_TO_VIDEO,
        req=req,
        auth=auth,
        store=store,
        usage=usage,
        enqueue=enqueue,
        queue_depth=queue_depth,
    )

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
from app.routers._shared import EnqueueDep, StoreDep, UsageDep, submit_job
from app.schemas.enums import ServiceType
from app.schemas.requests import MediaKitRequest
from app.schemas.responses import JobAccepted

router = APIRouter(prefix="/v1", tags=["media-kit"])


@router.post("/media-kit", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_media_kit(
    req: MediaKitRequest,
    auth: Auth,
    store: StoreDep,
    usage: UsageDep,
    enqueue: EnqueueDep,
) -> JobAccepted:
    return await submit_job(
        service=ServiceType.MEDIA_KIT,
        req=req,
        auth=auth,
        store=store,
        usage=usage,
        enqueue=enqueue,
    )

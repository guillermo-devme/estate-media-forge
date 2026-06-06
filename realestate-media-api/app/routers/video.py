"""Standalone image-to-video submit endpoint (same client_ref idempotency)."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import Auth
from app.routers._shared import EnqueueDep, StoreDep, UsageDep, submit_job
from app.schemas.enums import ServiceType
from app.schemas.requests import ImageToVideoRequest
from app.schemas.responses import JobAccepted

router = APIRouter(prefix="/v1", tags=["image-to-video"])


@router.post("/image-to-video", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_image_to_video(
    req: ImageToVideoRequest,
    auth: Auth,
    store: StoreDep,
    usage: UsageDep,
    enqueue: EnqueueDep,
) -> JobAccepted:
    return await submit_job(
        service=ServiceType.IMAGE_TO_VIDEO,
        req=req,
        auth=auth,
        store=store,
        usage=usage,
        enqueue=enqueue,
    )

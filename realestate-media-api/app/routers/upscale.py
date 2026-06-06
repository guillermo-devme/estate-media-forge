"""Standalone upscale submit endpoint (same client_ref idempotency)."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import Auth
from app.routers._shared import EnqueueDep, StoreDep, UsageDep, submit_job
from app.schemas.enums import ServiceType
from app.schemas.requests import UpscaleRequest
from app.schemas.responses import JobAccepted

router = APIRouter(prefix="/v1", tags=["upscale"])


@router.post("/upscale", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_upscale(
    req: UpscaleRequest,
    auth: Auth,
    store: StoreDep,
    usage: UsageDep,
    enqueue: EnqueueDep,
) -> JobAccepted:
    return await submit_job(
        service=ServiceType.UPSCALE,
        req=req,
        auth=auth,
        store=store,
        usage=usage,
        enqueue=enqueue,
    )

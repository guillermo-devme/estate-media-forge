"""Shared router dependencies + the idempotent submit flow.

Submit endpoints trust the HMAC-verified ``member_id`` (prompt 06), record usage,
and enqueue. NO balance check / 402 — affordability is Wix's job.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status

from app.deps import AuthContext
from app.jobs.store import JobStore
from app.schemas.enums import ServiceType
from app.schemas.requests import ImageToVideoRequest, MediaKitRequest, UpscaleRequest
from app.schemas.responses import JobAccepted
from app.wallet.models import UsageEventType
from app.wallet.repository import UsageRepository

SubmitRequest = MediaKitRequest | UpscaleRequest | ImageToVideoRequest
Enqueuer = Callable[[str, str], Awaitable[object]]


# ── Providers (resources live on app.state; overridable in tests) ───────────────
def get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store


def get_usage_repo(request: Request) -> UsageRepository:
    return request.app.state.usage


def get_enqueue(request: Request) -> Enqueuer:
    return request.app.state.enqueue


StoreDep = Annotated[JobStore, Depends(get_job_store)]
UsageDep = Annotated[UsageRepository, Depends(get_usage_repo)]
EnqueueDep = Annotated[Enqueuer, Depends(get_enqueue)]


def poll_url(job_id: str) -> str:
    return f"/v1/jobs/{job_id}"


async def submit_job(
    *,
    service: ServiceType,
    req: SubmitRequest,
    auth: AuthContext,
    store: JobStore,
    usage: UsageRepository,
    enqueue: Enqueuer,
) -> JobAccepted:
    """Idempotent submit: one job per (member_id, client_ref); 202 JobAccepted.

    Order matters for correctness under concurrent retries:
      1) fast path — if a job already exists for this client_ref, return it
         (no new job, no usage, no enqueue);
      2) else claim via SETNX (create_job_idempotent). Only the winner records
         usage + enqueues, so a lost race never double-charges or double-spends.
    """
    # member_id is already HMAC-bound (prompt 06); defensive equality guard.
    if req.member_id != auth.member_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    existing_id = await store.get_job_by_client_ref(auth.member_id, req.client_ref)
    if existing_id:
        job = await store.get_job(existing_id)
        return JobAccepted(
            job_id=existing_id,
            status=(job or {}).get("status", "queued"),
            service=service,
            poll_url=poll_url(existing_id),
            quoted_credits=req.quoted_credits,
        )

    job_id = f"job_{uuid4().hex}"
    aspect_ratios = [r.value for r in req.aspect_ratios]
    new_id, created = await store.create_job_idempotent(
        job_id=job_id,
        member_id=auth.member_id,
        service=service.value,
        request=req.model_dump(mode="json"),
        client_ref=req.client_ref,
        quoted_credits=req.quoted_credits,
        aspect_ratios=aspect_ratios,
    )

    if created:
        await usage.record_event(
            member_id=auth.member_id,
            job_id=new_id,
            service=service,
            event_type=UsageEventType.SUBMITTED,
            credits_quoted=req.quoted_credits,
            credits_charged=req.quoted_credits,
            note=f"client_ref={req.client_ref}",
        )
        await enqueue(service.value, new_id)
        status_value = "queued"
    else:
        # Lost the SETNX race; map to the winner without re-enqueuing.
        job = await store.get_job(new_id)
        status_value = (job or {}).get("status", "queued")

    return JobAccepted(
        job_id=new_id,
        status=status_value,
        service=service,
        poll_url=poll_url(new_id),
        quoted_credits=req.quoted_credits,
    )

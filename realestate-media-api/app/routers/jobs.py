"""Job status reads (ownership-enforced) + client_ref reconciliation lookup."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import Auth
from app.routers._shared import StoreDep
from app.schemas.responses import JobStatusResponse

router = APIRouter(prefix="/v1", tags=["jobs"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


# Registered before /jobs/{job_id} so the literal path wins.
@router.get(
    "/jobs/by-client-ref/{client_ref}",
    response_model=JobStatusResponse,
    summary="Resolve a job by client_ref",
    description="Reconciliation primitive: find the caller's job for a client_ref (404 if none).",
)
async def get_job_by_client_ref(client_ref: str, auth: Auth, store: StoreDep) -> JobStatusResponse:
    """Reconciliation primitive: resolve a member's job by its client_ref."""
    job_id = await store.get_job_by_client_ref(auth.member_id, client_ref)
    if not job_id:
        raise _NOT_FOUND
    job = await store.get_job(job_id)
    if job is None or job.get("member_id") != auth.member_id:
        raise _NOT_FOUND
    return JobStatusResponse.model_validate(job)


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Status + per-ratio assets + quoted/refunded credits. "
    "Returns 404 unless the job belongs to the signed member.",
)
async def get_job_status(job_id: str, auth: Auth, store: StoreDep) -> JobStatusResponse:
    job = await store.get_job(job_id)
    # 404 (not 403) on ownership mismatch — no cross-member enumeration.
    if job is None or job.get("member_id") != auth.member_id:
        raise _NOT_FOUND
    return JobStatusResponse.model_validate(job)

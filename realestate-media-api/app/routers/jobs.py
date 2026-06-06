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
    description="""Reconciliation primitive: find the caller's job by its `client_ref`.

**Purpose:** After an ambiguous submit timeout, Wix doesn't know if the job was created. This
endpoint lets it check: "did my submit with this `client_ref` actually land?" If yes → keep the
decrement and poll the job. If 404 → the submit never landed; refund the held credits.

**Use case — Wix `reconcileSubmit` sweep:**

```
 Wix PendingSubmits sweep
   │ for each stale intent (clientRef, memberId, quotedCredits):
   ▼
 GET /v1/jobs/by-client-ref/{clientRef}
   ├── 200 {job_id, status, ...} → job exists! Record ownership, clear intent.
   └── 404                       → submit never landed. Refund quotedCredits, clear intent.
```

Ownership-enforced: only the signed `member_id` can resolve their own `client_ref`.
""",
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
    description="""Poll a job's status, per-ratio assets, and credits charged/refunded.

**Purpose:** The only way for Wix to track the job after submit. Returns the current status
(`queued` → `running` → `completed`/`partial`/`failed`), the generated asset URLs per ratio,
and the refund accounting (so the frontend knows if credits came back).

**Use case — polling loop on the Generator page:**

1. Member submitted a media kit → got back `job_id` + `poll_url`.
2. Frontend polls every 3 seconds: `getJobStatus(jobId)` → Velo → `GET /v1/jobs/{job_id}`.
3. On `completed`: all 3 ratios have `video_url` → persist to Wix Media → render.
4. On `partial`: some ratios have media, failed ones show an error. `refunded_credits > 0`
   means the worker already refunded the failed portion back to Wix.
5. On `failed`: full refund sent to Wix; frontend shows error + updated balance.

```
 Frontend          Velo               FastAPI /v1/jobs/{id}          Worker
 ────────          ────               ─────────────────────          ──────
 poll (3s) ──────▶ ownership check
                   GET /v1/jobs/{id} ─▶ load from Redis ◀─────────── updates per ratio
                   ◀──── { status, assets[], quoted, refunded }
                   persist to Wix Media (if terminal)
 ◀── render assets (permanent wixstatic URLs)
```

**Ownership:** Returns 404 (not 403) if `job.member_id ≠ auth.member_id` — no cross-member
enumeration. A member can only see their own jobs.
""",
)
async def get_job_status(job_id: str, auth: Auth, store: StoreDep) -> JobStatusResponse:
    job = await store.get_job(job_id)
    # 404 (not 403) on ownership mismatch — no cross-member enumeration.
    if job is None or job.get("member_id") != auth.member_id:
        raise _NOT_FOUND
    return JobStatusResponse.model_validate(job)

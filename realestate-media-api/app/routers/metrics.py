"""Lightweight operational metrics (Auth)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import Auth
from app.obs.spans import span_ctx
from app.providers import fal_client
from app.routers._shared import ArqPoolDep, StoreDep

router = APIRouter(prefix="/v1", tags=["metrics"])


class MetricsLite(BaseModel):
    """Best-effort operational counters (credits-only domain; no USD)."""

    queue_depth: int = Field(..., description="Jobs waiting in the ARQ queue.")
    active_jobs: int = Field(..., description="Jobs currently in progress.")
    fal_semaphore: dict[str, int] = Field(
        ..., description="fal concurrency {limit,in_use,available}."
    )
    refund_failures: int = Field(..., description="Count of failed Wix refund callbacks.")


@router.get(
    "/metrics-lite",
    response_model=MetricsLite,
    summary="Lightweight operational metrics",
    description="Queue depth, active jobs, fal concurrency, and failed-refund count.",
)
async def metrics_lite(auth: Auth, store: StoreDep, pool: ArqPoolDep) -> MetricsLite:
    async with span_ctx("metrics.lite"):
        queue_depth = 0
        if pool is not None:
            try:
                queue_depth = len(await pool.queued_jobs())
            except Exception:  # noqa: BLE001 - metrics are best-effort
                queue_depth = 0

        try:
            active_jobs = await store.active_job_count()
        except Exception:  # noqa: BLE001
            active_jobs = 0

        try:
            refund_failures = await store.get_refund_failures()
        except Exception:  # noqa: BLE001
            refund_failures = 0

        return MetricsLite(
            queue_depth=queue_depth,
            active_jobs=active_jobs,
            fal_semaphore=fal_client.semaphore_stats(),
            refund_failures=refund_failures,
        )

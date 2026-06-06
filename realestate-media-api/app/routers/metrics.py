"""Lightweight operational metrics (Auth)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import Auth
from app.obs.spans import span_ctx
from app.providers import fal_client
from app.providers.fal_balance import circuit as fal_circuit
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
    fal_circuit_open: bool = Field(
        ..., description="True if fal provider capacity is exhausted (503 on submit)."
    )
    fal_balance_usd: float | None = Field(
        None, description="Last known fal account balance (None if unchecked)."
    )


@router.get(
    "/metrics-lite",
    response_model=MetricsLite,
    summary="Lightweight operational metrics",
    description="""Operational counters for monitoring the system health.

**Purpose:** Gives Wix (or an ops dashboard) visibility into queue pressure, worker load, and
money-owed situations (failed refunds). Useful for deciding whether to back off submissions
or alert on stuck refunds.

**Counters returned:**
- `queue_depth` — jobs waiting in the ARQ queue (Redis). High = workers are saturated.
- `active_jobs` — jobs currently in-progress (being processed by workers).
- `fal_semaphore` — `{limit, in_use, available}`: how much of the fal concurrency budget is consumed.
- `refund_failures` — cumulative count of failed Wix refund callbacks. **Non-zero means money is
  owed back to members.** Alert and investigate immediately.

**Use case — ops monitoring / Wix adaptive backoff:**

```
 Ops dashboard / Wix      FastAPI /v1/metrics-lite
 ─────────────────────    ───────────────────────
 periodic poll ─────────▶ read Redis counters + semaphore
 ◀── { queue_depth: 12, active_jobs: 8, fal_semaphore: {limit:8, in_use:6, available:2},
       refund_failures: 0 }
 if queue_depth > threshold → slow down submissions
 if refund_failures > 0    → alert: money owed back
```
""",
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
            fal_circuit_open=fal_circuit.is_open,
            fal_balance_usd=fal_circuit.last_balance_usd,
        )

"""Health + readiness probes (no auth)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.routers._shared import StoreDep, UsageDep

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/v1/ready", summary="Readiness probe (pings Redis + ledger)")
async def ready(store: StoreDep, usage: UsageDep) -> dict[str, object]:
    """Ping Redis + the usage ledger."""
    try:
        await store.ping()
        await usage.ping()
    except Exception as exc:  # noqa: BLE001 - readiness must not leak internals
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="not ready"
        ) from exc
    return {"status": "ready", "redis": True, "ledger": True}

"""ARQ worker: fan-out per ratio, then proportional refund to Wix on failure.

The worker NEVER debits — Wix already decremented at submit. On partial/total
failure it refunds exactly the failed ratios' credits via the Wix falRefund
http-function (HMAC-signed, idempotent on refund_{job_id}).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import RATIO_DIMS, get_settings
from app.jobs.enqueue import redis_settings
from app.jobs.store import JobStore
from app.obs.logging import get_logger
from app.obs.spans import set_job_context
from app.pipeline.graph import run_pipeline
from app.pipeline.tools import i2v_tool, upscale_tool
from app.providers.wix_client import WixRefundClient
from app.schemas.requests import CINEMATIC_PROMPT_TEMPLATE
from app.wallet.models import UsageEventType
from app.wallet.quotation import ratio_credits  # the ONE canonical per-ratio unit
from app.wallet.repository import UsageRepository

_logger = get_logger("app.worker")


# ── Media persistence (download fal outputs, rewrite to local /media URLs) ──────
async def save_pipeline_outputs(
    job_id: str, aspect_ratio: str, state: dict, *, client: httpx.AsyncClient | None = None
) -> dict:
    """Download produced assets to MEDIA_DIR/{job_id}/{ratio}/ and rewrite URLs."""
    settings = get_settings()
    safe_ratio = aspect_ratio.replace(":", "x")
    dest_dir = Path(settings.media_dir) / job_id / safe_ratio
    dest_dir.mkdir(parents=True, exist_ok=True)

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    rewritten: dict[str, str] = {}
    try:
        for key, label in (
            ("upscaled_url", "upscaled"),
            ("expanded_url", "expanded"),
            ("video_url", "video"),
        ):
            url = state.get(key)
            if not url:
                continue
            ext = os.path.splitext(urlparse(url).path)[1] or (
                ".mp4" if key == "video_url" else ".png"
            )
            filename = f"{label}{ext}"
            response = await client.get(url)
            response.raise_for_status()
            (dest_dir / filename).write_bytes(response.content)
            rewritten[key] = f"{settings.public_base_url}/media/{job_id}/{safe_ratio}/{filename}"
    finally:
        if own_client:
            await client.aclose()
    return rewritten


# ── Per-ratio execution ─────────────────────────────────────────────────────────
def _build_state(job_id: str, aspect_ratio: str, request: dict, prompt: str) -> dict:
    width, height = RATIO_DIMS.get(aspect_ratio, (1080, 1080))
    return {
        "job_id": job_id,
        "aspect_ratio": aspect_ratio,
        "room_name": request.get("room_name", ""),
        "source_image_url": request.get("image_url"),
        "upscale_factor": request.get("upscale_factor", 2),
        "do_expand": request.get("do_expand", True),
        "duration_seconds": request.get("duration_seconds", 5),
        "prompt": prompt,
        "target_w": width,
        "target_h": height,
    }


async def _run_ratio_state(service: str, state: dict) -> dict:
    """Run the appropriate stages for a service (media_kit = full graph; others short-circuit)."""
    if service == "media_kit":
        return await run_pipeline(state)
    if service == "upscale":
        try:
            out = await upscale_tool.ainvoke(
                {"image_url": state["source_image_url"], "upscale_factor": state["upscale_factor"]}
            )
            return {**state, "upscaled_url": out["upscaled_url"], "token_usage": {}}
        except Exception as exc:
            return {**state, "error": f"upscale failed: {exc}"}
    # image_to_video
    try:
        out = await i2v_tool.ainvoke(
            {
                "image_url": state["source_image_url"],
                "prompt": state["prompt"],
                "duration_seconds": state["duration_seconds"],
                "aspect_ratio": state["aspect_ratio"],
            }
        )
        return {**state, "video_url": out["video_url"], "token_usage": {}}
    except Exception as exc:
        return {**state, "error": f"i2v failed: {exc}"}


async def _process_ratio(
    store: JobStore,
    usage: UsageRepository,
    job_id: str,
    member_id: str,
    service: str,
    aspect_ratio: str,
    request: dict,
    prompt: str,
) -> tuple[str, bool]:
    set_job_context(job_id, aspect_ratio)
    state = _build_state(job_id, aspect_ratio, request, prompt)
    result = await _run_ratio_state(service, state)

    if result.get("error"):
        await store.update_asset(
            job_id, aspect_ratio, status="failed", error=str(result["error"])[:500]
        )
        await usage.record_event(
            member_id=member_id,
            job_id=job_id,
            service=service,
            event_type=UsageEventType.RATIO_FAILED,
            ratio=aspect_ratio,
            note=str(result["error"])[:200],
        )
        return aspect_ratio, False

    urls = await save_pipeline_outputs(job_id, aspect_ratio, result)
    await store.update_asset(job_id, aspect_ratio, status="completed", **urls)
    await usage.record_event(
        member_id=member_id,
        job_id=job_id,
        service=service,
        event_type=UsageEventType.RATIO_SUCCEEDED,
        ratio=aspect_ratio,
    )
    return aspect_ratio, True


# ── Settlement ──────────────────────────────────────────────────────────────────
#  Refund decision tree
#   job outcome?
#     ├─ completed (all ratios ok) ─▶ refund 0
#     ├─ partial  (k of n failed)  ─▶ refund Σ credits(failed k ratios)
#     └─ failed   (all n failed)   ─▶ refund Σ credits(all ratios) == full
async def _settle(
    store: JobStore,
    usage: UsageRepository,
    refund_client: WixRefundClient,
    *,
    job_id: str,
    member_id: str,
    service: str,
    quoted_credits: int,
    failed_ratios: list[str],
    total_ratios: int,
    params: dict,
) -> None:
    if not member_id or not quoted_credits or not failed_ratios:
        return

    refund_credits = sum(
        ratio_credits(
            service,
            ratio,
            duration_seconds=params["duration_seconds"],
            do_expand=params["do_expand"],
            upscale_factor=params["upscale_factor"],
        )
        for ratio in failed_ratios
    )

    # All ratios failed → full refund must equal the charge (reconciliation rule).
    if len(failed_ratios) == total_ratios and refund_credits != quoted_credits:
        _logger.error(
            "settlement.refund_mismatch",
            extra={"job_id": job_id, "computed": refund_credits, "quoted": quoted_credits},
        )

    # Defense in depth: never refund more than was charged (over-refund mints credits).
    refund_credits = min(refund_credits, quoted_credits)
    if refund_credits <= 0:
        return

    try:
        await refund_client.refund(member_id, job_id, refund_credits, reason="job_failed")
        await store.update_job(job_id, refunded_credits=refund_credits)
        await usage.record_event(
            member_id=member_id,
            job_id=job_id,
            service=service,
            event_type=UsageEventType.REFUND_REQUESTED,
            credits_refunded=refund_credits,
        )
    except Exception as exc:  # noqa: BLE001 - money is owed back; log loudly
        _logger.error(
            "settlement.refund_failed",
            extra={
                "job_id": job_id,
                "member_id": member_id,
                "refund_credits": refund_credits,
                "error": repr(exc),
            },
        )
        # Surface unbilled refunds in /v1/metrics-lite (cross-process counter).
        try:
            await store.incr_refund_failures()
        except Exception:  # noqa: BLE001 - metrics must never mask the real error
            pass


# ── Job entrypoints ───────────────────────────────────────────────────────────
async def _process_job(ctx: dict, job_id: str) -> dict:
    store: JobStore = ctx["store"]
    usage: UsageRepository = ctx["usage"]
    refund_client: WixRefundClient = ctx["refund_client"]

    job = await store.get_job(job_id)
    if job is None:
        _logger.warning("worker.job_missing", extra={"job_id": job_id})
        return {"job_id": job_id, "status": "missing"}

    member_id = job["member_id"]
    service = job["service"]
    quoted_credits = job.get("quoted_credits") or 0
    request = job.get("request", {})

    set_job_context(job_id)
    await store.set_status(job_id, "running")
    await usage.record_event(
        member_id=member_id,
        job_id=job_id,
        service=service,
        event_type=UsageEventType.SUBMITTED,
        credits_quoted=quoted_credits,
        credits_charged=quoted_credits,
    )

    ratios = [asset["aspect_ratio"] for asset in job.get("assets", [])]
    prompt = request.get("prompt_override") or CINEMATIC_PROMPT_TEMPLATE.format(
        room_name=request.get("room_name", "")
    )
    params = {
        "duration_seconds": request.get("duration_seconds", 5),
        "do_expand": request.get("do_expand", True),
        "upscale_factor": request.get("upscale_factor", 2),
    }

    # Fan out; real concurrency is capped by the fal semaphore in the client.
    outcomes = await asyncio.gather(
        *(
            _process_ratio(store, usage, job_id, member_id, service, ratio, request, prompt)
            for ratio in ratios
        )
    )
    failed = [ratio for ratio, ok in outcomes if not ok]

    if not failed:
        status = "completed"
    elif len(failed) == len(ratios):
        status = "failed"
    else:
        status = "partial"
    await store.set_status(job_id, status)

    await _settle(
        store,
        usage,
        refund_client,
        job_id=job_id,
        member_id=member_id,
        service=service,
        quoted_credits=quoted_credits,
        failed_ratios=failed,
        total_ratios=len(ratios),
        params=params,
    )
    return {"job_id": job_id, "status": status, "failed": failed}


async def process_media_job(ctx: dict, job_id: str) -> dict:
    return await _process_job(ctx, job_id)


async def process_upscale_job(ctx: dict, job_id: str) -> dict:
    return await _process_job(ctx, job_id)


async def process_i2v_job(ctx: dict, job_id: str) -> dict:
    return await _process_job(ctx, job_id)


# ── ARQ wiring ────────────────────────────────────────────────────────────────
async def on_startup(ctx: dict) -> None:
    usage = UsageRepository()
    await usage.create_all()
    ctx["store"] = JobStore()
    ctx["usage"] = usage
    ctx["refund_client"] = WixRefundClient()


async def on_shutdown(ctx: dict) -> None:
    store = ctx.get("store")
    if store is not None:
        await store.aclose()
    usage = ctx.get("usage")
    if usage is not None:
        await usage.dispose()


class WorkerSettings:
    """ARQ worker configuration (run with `arq app.jobs.worker.WorkerSettings`)."""

    functions = [process_media_job, process_upscale_job, process_i2v_job]
    redis_settings = redis_settings()
    max_jobs = 20
    job_timeout = 1800  # 30 min ceiling per job
    keep_result = 3600  # keep ARQ result 1h
    health_check_interval = 30  # worker health record cadence (seconds)
    on_startup = on_startup
    on_shutdown = on_shutdown

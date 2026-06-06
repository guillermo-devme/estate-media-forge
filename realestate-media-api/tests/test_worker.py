"""Worker fan-out + proportional refund settlement."""

from __future__ import annotations

import copy

import pytest

import app.jobs.worker as worker
import app.providers.fal_client as fal
from app.wallet.models import UsageEventType
from app.wallet.quotation import ratio_credits


class FakeJobStore:
    def __init__(self, record: dict) -> None:
        self.jobs = {record["job_id"]: record}

    async def get_job(self, job_id):
        job = self.jobs.get(job_id)
        return copy.deepcopy(job) if job else None

    async def set_status(self, job_id, status):
        self.jobs[job_id]["status"] = status
        return self.jobs[job_id]

    async def update_job(self, job_id, **fields):
        self.jobs[job_id].update(fields)
        return self.jobs[job_id]

    async def update_asset(self, job_id, aspect_ratio, **fields):
        for asset in self.jobs[job_id]["assets"]:
            if asset["aspect_ratio"] == aspect_ratio:
                asset.update(fields)
        return self.jobs[job_id]


class FakeUsage:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record_event(self, **kwargs):
        self.events.append(kwargs)


class FakeRefund:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def refund(self, member_id, job_id, credits, reason="job_failed"):
        self.calls.append((member_id, job_id, credits, reason))
        return {"ok": True, "refunded": credits}


def _record(service="media_kit", ratios=("1:1", "9:16", "16:9"), quoted=3366) -> dict:
    return {
        "job_id": "job_1",
        "member_id": "mem_1",
        "service": service,
        "status": "queued",
        "request": {
            "image_url": "https://example.com/a.jpg",
            "room_name": "den",
            "aspect_ratios": list(ratios),
            "do_expand": True,
            "upscale_factor": 2,
            "duration_seconds": 5,
        },
        "assets": [
            {
                "aspect_ratio": r,
                "upscaled_url": None,
                "expanded_url": None,
                "video_url": None,
                "status": "queued",
                "error": None,
            }
            for r in ratios
        ],
        "client_ref": "spend_1",
        "quoted_credits": quoted,
        "refunded_credits": 0,
        "token_usage": None,
        "error": None,
        "created_at": "t",
        "updated_at": "t",
    }


@pytest.fixture
def ctx_and_fakes(monkeypatch):
    store = FakeJobStore(_record())
    usage = FakeUsage()
    refund = FakeRefund()
    ctx = {"store": store, "usage": usage, "refund_client": refund}

    # Avoid real media download.
    async def fake_save(job_id, aspect_ratio, state, client=None):
        return {"video_url": f"http://media/{job_id}/{aspect_ratio}.mp4"}

    monkeypatch.setattr(worker, "save_pipeline_outputs", fake_save)
    return ctx, store, usage, refund


async def test_partial_refunds_exactly_failed_ratio(ctx_and_fakes, monkeypatch):
    ctx, store, usage, refund = ctx_and_fakes

    async def fake_pipeline(state):
        if state["aspect_ratio"] == "9:16":
            return {**state, "error": "i2v failed: boom"}
        return {**state, "upscaled_url": "u", "expanded_url": "e", "video_url": "v"}

    monkeypatch.setattr(worker, "run_pipeline", fake_pipeline)

    result = await worker.process_media_job(ctx, "job_1")

    assert result["status"] == "partial"
    assert store.jobs["job_1"]["status"] == "partial"

    expected = ratio_credits(
        "media_kit", "9:16", duration_seconds=5, do_expand=True, upscale_factor=2
    )
    assert refund.calls == [("mem_1", "job_1", expected, "job_failed")]
    assert store.jobs["job_1"]["refunded_credits"] == expected

    refund_events = [e for e in usage.events if e["event_type"] == UsageEventType.REFUND_REQUESTED]
    assert refund_events and refund_events[0]["credits_refunded"] == expected


async def test_full_success_triggers_no_refund(ctx_and_fakes, monkeypatch):
    ctx, store, usage, refund = ctx_and_fakes

    async def fake_pipeline(state):
        return {**state, "upscaled_url": "u", "expanded_url": "e", "video_url": "v"}

    monkeypatch.setattr(worker, "run_pipeline", fake_pipeline)

    result = await worker.process_media_job(ctx, "job_1")
    assert result["status"] == "completed"
    assert refund.calls == []
    assert store.jobs["job_1"]["refunded_credits"] == 0


async def test_total_failure_refunds_full_quoted(ctx_and_fakes, monkeypatch):
    ctx, store, usage, refund = ctx_and_fakes

    async def fake_pipeline(state):
        return {**state, "error": "i2v failed: down"}

    monkeypatch.setattr(worker, "run_pipeline", fake_pipeline)

    result = await worker.process_media_job(ctx, "job_1")
    assert result["status"] == "failed"
    # All ratios failed → full refund equals the quoted charge.
    assert refund.calls[0][2] == store.jobs["job_1"]["quoted_credits"] == 3366


async def test_upscale_single_asset_failure_refunds_full(monkeypatch):
    quoted = ratio_credits("upscale", "1:1")
    store = FakeJobStore(_record(service="upscale", ratios=("1:1",), quoted=quoted))
    usage = FakeUsage()
    refund = FakeRefund()
    ctx = {"store": store, "usage": usage, "refund_client": refund}

    async def boom_upscale(image_url, factor):
        raise RuntimeError("fal down")

    monkeypatch.setattr(fal, "run_upscale", boom_upscale)

    result = await worker.process_upscale_job(ctx, "job_1")
    assert result["status"] == "failed"
    assert refund.calls == [("mem_1", "job_1", quoted, "job_failed")]

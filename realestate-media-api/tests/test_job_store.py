"""Job store: client_ref idempotency (SETNX) creates exactly one job."""

from __future__ import annotations

from app.jobs.store import JobStore


class FakeRedis:
    """Minimal in-memory Redis supporting set(nx, ex) and get."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)


def _store() -> tuple[JobStore, FakeRedis]:
    fake = FakeRedis()
    return JobStore(client=fake), fake


async def test_create_job_idempotent_is_exactly_once():
    store, fake = _store()
    kwargs = dict(
        member_id="mem_1",
        service="media_kit",
        request={"image_url": "https://x/a.jpg", "aspect_ratios": ["1:1", "9:16", "16:9"]},
        client_ref="spend_1",
        quoted_credits=3366,
        aspect_ratios=["1:1", "9:16", "16:9"],
    )

    job_id_1, created_1 = await store.create_job_idempotent(job_id="job_a", **kwargs)
    assert created_1 is True
    assert job_id_1 == "job_a"

    # Second submit with the SAME client_ref (different job_id) must map to the first.
    job_id_2, created_2 = await store.create_job_idempotent(job_id="job_b", **kwargs)
    assert created_2 is False
    assert job_id_2 == "job_a"

    # Exactly one job record exists (job_b was never written).
    job_keys = [k for k in fake.data if k.startswith("job:")]
    assert job_keys == ["job:job_a"]
    assert await store.get_job("job_b") is None


async def test_get_job_by_client_ref_and_updates():
    store, _ = _store()
    await store.create_job_idempotent(
        job_id="job_x",
        member_id="mem_1",
        service="media_kit",
        request={"aspect_ratios": ["1:1"]},
        client_ref="ref_9",
        quoted_credits=1122,
        aspect_ratios=["1:1"],
    )
    assert await store.get_job_by_client_ref("mem_1", "ref_9") == "job_x"
    assert await store.get_job_by_client_ref("mem_1", "nope") is None

    job = await store.get_job("job_x")
    assert job["status"] == "queued"
    assert len(job["assets"]) == 1

    await store.set_status("job_x", "running")
    await store.update_asset("job_x", "1:1", status="completed", video_url="http://m/v.mp4")
    job = await store.get_job("job_x")
    assert job["status"] == "running"
    assert job["assets"][0]["status"] == "completed"
    assert job["assets"][0]["video_url"] == "http://m/v.mp4"

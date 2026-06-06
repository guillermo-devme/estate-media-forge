"""Usage ledger is append-only and audit-only (no balance authority)."""

from __future__ import annotations

import pytest_asyncio

from app.schemas.enums import ServiceType
from app.wallet.models import UsageEventType
from app.wallet.repository import UsageRepository


@pytest_asyncio.fixture
async def repo(tmp_path):
    repository = UsageRepository(dsn=f"sqlite+aiosqlite:///{tmp_path}/usage.db")
    await repository.create_all()
    try:
        yield repository
    finally:
        await repository.dispose()


async def _seed_job(repo: UsageRepository, job_id: str, member_id: str) -> None:
    await repo.record_event(
        member_id=member_id,
        job_id=job_id,
        service=ServiceType.MEDIA_KIT,
        event_type=UsageEventType.SUBMITTED,
        credits_quoted=3366,
        credits_charged=3366,
    )
    await repo.record_event(
        member_id=member_id,
        job_id=job_id,
        service=ServiceType.MEDIA_KIT,
        event_type=UsageEventType.RATIO_SUCCEEDED,
        ratio="1:1",
    )
    await repo.record_event(
        member_id=member_id,
        job_id=job_id,
        service=ServiceType.MEDIA_KIT,
        event_type=UsageEventType.RATIO_SUCCEEDED,
        ratio="16:9",
    )
    await repo.record_event(
        member_id=member_id,
        job_id=job_id,
        service=ServiceType.MEDIA_KIT,
        event_type=UsageEventType.RATIO_FAILED,
        ratio="9:16",
        note="i2v timeout",
    )
    await repo.record_event(
        member_id=member_id,
        job_id=job_id,
        service=ServiceType.MEDIA_KIT,
        event_type=UsageEventType.REFUND_REQUESTED,
        credits_refunded=1122,
    )


async def test_reconcile_summary(repo):
    await _seed_job(repo, "job_1", "mem_1")
    summary = await repo.reconcile_summary("job_1")
    assert summary["quoted"] == 3366
    assert summary["charged"] == 3366
    assert summary["refunded"] == 1122
    assert summary["net_charged"] == 2244
    assert summary["events"] == 5


async def test_list_for_job_and_member(repo):
    await _seed_job(repo, "job_1", "mem_1")
    # An unrelated event for another job/member must not bleed in.
    await repo.record_event(
        member_id="mem_2",
        job_id="job_2",
        service=ServiceType.UPSCALE,
        event_type=UsageEventType.SUBMITTED,
        credits_charged=20,
    )

    job_events = await repo.list_for_job("job_1")
    assert len(job_events) == 5
    assert all(e.job_id == "job_1" for e in job_events)
    # Stored as plain enum values.
    assert job_events[0].event_type == "submitted"
    assert job_events[0].service == "media_kit"

    member_events = await repo.list_for_member("mem_1")
    assert len(member_events) == 5
    assert {e.member_id for e in member_events} == {"mem_1"}


def test_repository_exposes_no_balance_methods():
    forbidden = (
        "get_balance",
        "get_available",
        "hold",
        "reserve",
        "spend",
        "debit",
        "credit",
        "topup",
        "adjust_balance",
    )
    for name in forbidden:
        assert not hasattr(UsageRepository, name), f"audit-only ledger must not expose {name}"


async def test_summary_of_unknown_job_is_zeroed(repo):
    summary = await repo.reconcile_summary("does-not-exist")
    assert summary == {
        "job_id": "does-not-exist",
        "quoted": 0,
        "charged": 0,
        "refunded": 0,
        "net_charged": 0,
        "events": 0,
    }

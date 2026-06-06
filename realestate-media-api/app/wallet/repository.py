"""Async usage/audit ledger repository.

BALANCE AUTHORITY IS WIX CMS. This repository is intentionally audit-only: it
exposes NO get_balance / get_available / hold / spend methods. It only appends
usage events and summarizes them for reconciliation against Wix
``TokenTransactions``. The DSN is pluggable (default SQLite via
``settings.ledger_dsn``; point it at Postgres later).
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.obs.spans import span
from app.schemas.enums import ServiceType
from app.wallet.models import Base, UsageEvent, UsageEventType


def _value(item: Enum | str) -> str:
    return item.value if isinstance(item, Enum) else item


class UsageRepository:
    """Append-only usage ledger over an async SQLAlchemy engine."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or get_settings().ledger_dsn
        self._engine = create_async_engine(self._dsn, future=True)
        self._session = async_sessionmaker(self._engine, expire_on_commit=False)

    async def create_all(self) -> None:
        """Create the ledger tables if they do not exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """Dispose the engine / connection pool."""
        await self._engine.dispose()

    @span("usage.record_event")
    async def record_event(
        self,
        *,
        member_id: str,
        service: ServiceType | str,
        event_type: UsageEventType | str,
        job_id: str | None = None,
        credits_quoted: int = 0,
        credits_charged: int = 0,
        credits_refunded: int = 0,
        ratio: str | None = None,
        note: str | None = None,
    ) -> UsageEvent:
        """Append one usage event and return it."""
        event = UsageEvent(
            member_id=member_id,
            job_id=job_id,
            service=_value(service),
            event_type=_value(event_type),
            credits_quoted=credits_quoted,
            credits_charged=credits_charged,
            credits_refunded=credits_refunded,
            ratio=ratio,
            note=note,
        )
        async with self._session() as session:
            session.add(event)
            await session.commit()
            await session.refresh(event)
        return event

    async def list_for_job(self, job_id: str) -> list[UsageEvent]:
        """All events for a job, oldest first."""
        async with self._session() as session:
            stmt = (
                select(UsageEvent)
                .where(UsageEvent.job_id == job_id)
                .order_by(UsageEvent.id.asc())
            )
            return list((await session.execute(stmt)).scalars().all())

    async def list_for_member(self, member_id: str) -> list[UsageEvent]:
        """All events for a member, oldest first."""
        async with self._session() as session:
            stmt = (
                select(UsageEvent)
                .where(UsageEvent.member_id == member_id)
                .order_by(UsageEvent.id.asc())
            )
            return list((await session.execute(stmt)).scalars().all())

    @span("usage.reconcile_summary")
    async def reconcile_summary(self, job_id: str) -> dict:
        """Quoted vs charged vs refunded totals for a job (audit, not authority)."""
        async with self._session() as session:
            stmt = select(
                func.coalesce(func.sum(UsageEvent.credits_quoted), 0),
                func.coalesce(func.sum(UsageEvent.credits_charged), 0),
                func.coalesce(func.sum(UsageEvent.credits_refunded), 0),
                func.count(UsageEvent.id),
            ).where(UsageEvent.job_id == job_id)
            quoted, charged, refunded, events = (await session.execute(stmt)).one()
        return {
            "job_id": job_id,
            "quoted": int(quoted),
            "charged": int(charged),
            "refunded": int(refunded),
            "net_charged": int(charged) - int(refunded),
            "events": int(events),
        }

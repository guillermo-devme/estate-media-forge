"""Append-only usage/audit ledger models.

BALANCE AUTHORITY IS WIX CMS. This service owns no balance, holds, or
``available`` — it records an append-only stream of usage events for
observability, reconciliation against Wix ``TokenTransactions``, and per-ratio
refund accounting only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for ledger models."""


class UsageEventType(str, Enum):
    """The lifecycle events we append to the ledger."""

    QUOTED = "quoted"
    SUBMITTED = "submitted"
    RATIO_SUCCEEDED = "ratio_succeeded"
    RATIO_FAILED = "ratio_failed"
    REFUND_REQUESTED = "refund_requested"
    SETTLED = "settled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UsageEvent(Base):
    """One append-only audit row. Credits only — never USD."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(String(128), index=True)
    # Nullable: a `quoted` event happens before a job exists.
    job_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    service: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    credits_quoted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_charged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_refunded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"UsageEvent(id={self.id}, member_id={self.member_id!r}, job_id={self.job_id!r}, "
            f"event_type={self.event_type!r}, ratio={self.ratio!r})"
        )

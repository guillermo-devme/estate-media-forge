"""Redis-backed job records + client_ref idempotency index.

DURABILITY: job records AND the ARQ queue both live in Redis, so job state
survives only as long as Redis does. For local/dev this is fine; for any real
use Redis MUST run with persistence (AOF/RDB) or a restart loses in-flight jobs
that were already charged Wix-side. The 24h TTL is a dev convenience — the
generated media and the Wix Jobs ownership row outlive it. Redis is NOT the
durable record of truth (the Wix CMS ledger is). See
../../docs/kiro-prompts/INDEX.md "Durability & deployment scope".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as redis_asyncio

from app.config import get_settings

JOB_TTL_SECONDS = 24 * 60 * 60  # 24h dev convenience


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


def _clientref_key(member_id: str, client_ref: str) -> str:
    return f"clientref:{member_id}:{client_ref}"


class JobStore:
    """Job records keyed by ``job:{job_id}`` with a ``clientref:`` idempotency index."""

    def __init__(self, client=None) -> None:  # noqa: ANN001 - redis.asyncio.Redis
        self._redis = client

    @property
    def redis(self):
        if self._redis is None:
            self._redis = redis_asyncio.from_url(get_settings().redis_url, decode_responses=True)
        return self._redis

    async def aclose(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def ping(self) -> bool:
        """Liveness check for the readiness probe."""
        return bool(await self.redis.ping())

    @staticmethod
    def _build_record(
        *,
        job_id: str,
        member_id: str,
        service: str,
        request: dict,
        client_ref: str,
        quoted_credits: int,
        aspect_ratios: list[str],
    ) -> dict:
        now = _now()
        return {
            "job_id": job_id,
            "member_id": member_id,
            "service": service,
            "status": "queued",
            "request": request,
            "assets": [
                {
                    "aspect_ratio": ratio,
                    "upscaled_url": None,
                    "expanded_url": None,
                    "video_url": None,
                    "status": "queued",
                    "error": None,
                }
                for ratio in aspect_ratios
            ],
            "client_ref": client_ref,
            "quoted_credits": quoted_credits,
            "refunded_credits": 0,
            "token_usage": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

    async def _save(self, record: dict) -> None:
        await self.redis.set(_job_key(record["job_id"]), json.dumps(record), ex=JOB_TTL_SECONDS)

    async def create_job_idempotent(
        self,
        *,
        job_id: str,
        member_id: str,
        service: str,
        request: dict,
        client_ref: str,
        quoted_credits: int,
        aspect_ratios: list[str],
    ) -> tuple[str, bool]:
        """Create a job exactly-once per (member_id, client_ref).

        Returns ``(job_id, created)``. If a job already exists for this
        client_ref, returns the existing job_id with ``created=False`` and does
        NOT write a second record.
        """
        idem_key = _clientref_key(member_id, client_ref)
        claimed = await self.redis.set(idem_key, job_id, nx=True, ex=JOB_TTL_SECONDS)
        if not claimed:
            existing = await self.redis.get(idem_key)
            return existing, False

        record = self._build_record(
            job_id=job_id,
            member_id=member_id,
            service=service,
            request=request,
            client_ref=client_ref,
            quoted_credits=quoted_credits,
            aspect_ratios=aspect_ratios,
        )
        await self._save(record)
        return job_id, True

    async def get_job(self, job_id: str) -> dict | None:
        raw = await self.redis.get(_job_key(job_id))
        return json.loads(raw) if raw else None

    async def get_job_by_client_ref(self, member_id: str, client_ref: str) -> str | None:
        return await self.redis.get(_clientref_key(member_id, client_ref))

    async def update_job(self, job_id: str, **fields) -> dict | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        job.update(fields)
        job["updated_at"] = _now()
        await self._save(job)
        return job

    async def set_status(self, job_id: str, status: str) -> dict | None:
        return await self.update_job(job_id, status=status)

    async def update_asset(self, job_id: str, aspect_ratio: str, **fields) -> dict | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        for asset in job.get("assets", []):
            if asset.get("aspect_ratio") == aspect_ratio:
                asset.update(fields)
                break
        job["updated_at"] = _now()
        await self._save(job)
        return job

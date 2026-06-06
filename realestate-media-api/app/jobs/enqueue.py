"""ARQ pool + enqueue helpers (maps service -> worker function)."""

from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings

# Service -> ARQ worker function name.
_SERVICE_TO_FUNCTION = {
    "media_kit": "process_media_job",
    "upscale": "process_upscale_job",
    "image_to_video": "process_i2v_job",
}

_pool = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_arq_pool():
    """Return the shared ARQ Redis pool (lazily constructed)."""
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue_job(service: str, job_id: str):
    """Enqueue the worker function matching ``service`` for ``job_id``."""
    function_name = _SERVICE_TO_FUNCTION.get(service)
    if function_name is None:
        raise ValueError(f"no worker function for service {service!r}")
    pool = await get_arq_pool()
    return await pool.enqueue_job(function_name, job_id)

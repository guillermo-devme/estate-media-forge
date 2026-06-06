"""Async fal.ai client over the QUEUE API (submit → poll → result).

Design:
- A module-level ``asyncio.Semaphore(max_fal_concurrency)`` caps real load on fal;
  it is held around every call.
- ``submit_and_wait`` submits to the fal queue, then polls the returned
  ``status_url`` (exponential backoff + jitter) until ``COMPLETED`` and returns
  the result payload from ``response_url``.
- Per-request transient failures (network / timeout / 5xx) are retried with
  tenacity (≤3, exponential + jitter); 4xx validation errors are raised
  immediately (never retried).
- A single shared ``httpx.AsyncClient`` carries the ``Authorization: Key`` header.

Queue conventions verified against the fal Queue OpenAPI (2026-06-05):
  submit  POST https://queue.fal.run/{endpoint_id}
  status  GET  {status_url}        (status ∈ IN_QUEUE | IN_PROGRESS | COMPLETED)
  result  GET  {response_url}
We use the ``status_url``/``response_url`` returned by submit so sub-endpoints
(e.g. ``fal-ai/flux-2-pro/outpaint``) resolve correctly.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.config import get_settings
from app.obs.logging import get_logger
from app.obs.spans import span_ctx

_logger = get_logger("app.fal")

_QUEUE_BASE = "https://queue.fal.run"

# Per-request transient retry (network/5xx). Tunable for tests.
_RETRY_ATTEMPTS = 3
_RETRY_MULTIPLIER = 0.5
_RETRY_MAX = 8.0

# Poll cadence between IN_QUEUE/IN_PROGRESS checks. Tunable for tests.
_POLL_BASE_DELAY = 1.0
_POLL_MAX_DELAY = 10.0
_POLL_JITTER = 0.5
_POLL_MAX_ATTEMPTS = 600  # safety cap to avoid an unbounded poll loop


class FalError(Exception):
    """Base error for fal interactions."""


class FalValidationError(FalError):
    """A 4xx from fal (bad arguments). Never retried."""


class FalTransientError(FalError):
    """A retryable failure (network/timeout/5xx/queue error)."""


# ── Shared client + concurrency gate ────────────────────────────────────────────
_client: httpx.AsyncClient | None = None
_semaphore = asyncio.Semaphore(get_settings().max_fal_concurrency)


def get_client() -> httpx.AsyncClient:
    """Return the shared fal HTTP client (lazily constructed)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            headers={"Authorization": f"Key {settings.fal_key}"},
        )
    return _client


async def aclose() -> None:
    """Close the shared client (call on app shutdown)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def semaphore_stats() -> dict[str, int]:
    """Best-effort fal concurrency stats for the metrics endpoint."""
    limit = get_settings().max_fal_concurrency
    available = _semaphore._value  # noqa: SLF001 - lite metric only
    return {"limit": limit, "available": available, "in_use": max(0, limit - available)}


# ── Low-level request with transient retry ──────────────────────────────────────
async def _request_once(
    method: str, url: str, *, json: dict | None, client: httpx.AsyncClient
) -> dict:
    try:
        response = await client.request(method, url, json=json)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise FalTransientError(f"network error calling fal: {exc!r}") from exc

    code = response.status_code
    if code >= 500:
        raise FalTransientError(f"fal upstream {code}")
    if code >= 400:
        # 4xx = bad arguments; surface immediately, do not retry.
        raise FalValidationError(f"fal rejected request ({code})")
    return response.json()


async def _request(
    method: str, url: str, *, json: dict | None = None, client: httpx.AsyncClient
) -> dict:
    """Issue a request, retrying only transient errors (≤ _RETRY_ATTEMPTS)."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_random_exponential(multiplier=_RETRY_MULTIPLIER, max=_RETRY_MAX),
        retry=retry_if_exception_type(FalTransientError),
        reraise=True,
    ):
        with attempt:
            return await _request_once(method, url, json=json, client=client)
    raise FalTransientError("unreachable")  # pragma: no cover


async def _sleep_backoff(attempt: int) -> None:
    delay = min(_POLL_MAX_DELAY, _POLL_BASE_DELAY * (2**attempt))
    await asyncio.sleep(delay + random.uniform(0, _POLL_JITTER))


# ── Public API ──────────────────────────────────────────────────────────────────
async def submit_and_wait(
    model_id: str, arguments: dict[str, Any], *, client: httpx.AsyncClient | None = None
) -> dict:
    """Submit to the fal queue and poll until COMPLETED; return the result payload."""
    client = client or get_client()
    async with _semaphore, span_ctx(f"fal.{model_id}"):
        status = await _request("POST", f"{_QUEUE_BASE}/{model_id}", json=arguments, client=client)
        request_id = status.get("request_id")
        status_url = status.get("status_url") or (
            f"{_QUEUE_BASE}/{model_id}/requests/{request_id}/status"
        )
        response_url = status.get("response_url") or (
            f"{_QUEUE_BASE}/{model_id}/requests/{request_id}"
        )
        _logger.info(
            "fal.submitted",
            extra={
                "model_id": model_id,
                "request_id": request_id,
                "queue_position": status.get("queue_position"),
            },
        )

        attempt = 0
        while status.get("status") != "COMPLETED":
            state = status.get("status")
            if state not in ("IN_QUEUE", "IN_PROGRESS"):
                raise FalError(f"unexpected fal status: {state!r}")
            if attempt >= _POLL_MAX_ATTEMPTS:
                raise FalTransientError("fal poll timeout")
            await _sleep_backoff(attempt)
            attempt += 1
            status = await _request("GET", status_url, client=client)
            _logger.debug(
                "fal.poll",
                extra={
                    "model_id": model_id,
                    "request_id": request_id,
                    "queue_position": status.get("queue_position"),
                },
            )

        result = await _request("GET", response_url, client=client)
        _logger.info("fal.completed", extra={"model_id": model_id, "request_id": request_id})
        return result


# ── Typed helpers mapping to config MODEL_REGISTRY ──────────────────────────────
# TODO(fal-args): confirm exact argument field names against the live model API
# pages before production — the model pages are the source of truth:
#   upscale  : https://fal.ai/models/fal-ai/clarity-upscaler/api
#   outpaint : https://fal.ai/models/fal-ai/flux-2-pro/outpaint/api
#   i2v      : https://fal.ai/models/bytedance/seedance-2.0/image-to-video/api
# `image_url` is confirmed for all three; the secondary fields below are best-effort.
async def run_upscale(image_url: str, factor: int) -> dict:
    """Upscale an image. Returns the fal result payload."""
    model_id = get_settings().MODEL_REGISTRY["upscale"]
    arguments = {
        "image_url": image_url,
        # TODO(fal-args): confirm scale field name (`upscale_factor` vs `scale_factor`).
        "upscale_factor": factor,
    }
    return await submit_and_wait(model_id, arguments)


async def run_outpaint(image_url: str, target_w: int, target_h: int) -> dict:
    """Expand/outpaint an image to a target canvas. Returns the fal result payload."""
    model_id = get_settings().MODEL_REGISTRY["outpaint"]
    arguments = {
        "image_url": image_url,
        # TODO(fal-args): confirm the target-size field for FLUX 2 Pro Outpaint
        # (`canvas_size` vs `image_size` vs directional expand margins).
        "canvas_size": {"width": target_w, "height": target_h},
    }
    return await submit_and_wait(model_id, arguments)


async def run_image_to_video(
    image_url: str, prompt: str, duration_seconds: int, aspect_ratio: str
) -> dict:
    """Generate a cinematic clip from an image. Returns the fal result payload."""
    model_id = get_settings().MODEL_REGISTRY["i2v"]
    arguments = {
        "image_url": image_url,
        "prompt": prompt,
        # TODO(fal-args): confirm field names + allowed values for Seedance 2.0:
        # `duration` is seconds (note: Seedance accepts 4–15s, while our request
        # schema allows 3–10 — reconcile the lower bound before production), and
        # add `resolution` ("480p"|"720p"|"1080p") if required for the target ratio.
        "duration": duration_seconds,
        "aspect_ratio": aspect_ratio,
    }
    return await submit_and_wait(model_id, arguments)

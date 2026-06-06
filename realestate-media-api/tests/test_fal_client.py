"""fal client: queue submit/poll, retry skips 4xx, retries transient 5xx."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import app.providers.fal_client as fal


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    # Make retry/poll instantaneous for tests.
    monkeypatch.setattr(fal, "_RETRY_MULTIPLIER", 0.0)
    monkeypatch.setattr(fal, "_RETRY_MAX", 0.0)
    monkeypatch.setattr(fal, "_POLL_BASE_DELAY", 0.0)
    monkeypatch.setattr(fal, "_POLL_JITTER", 0.0)
    monkeypatch.setattr(
        fal,
        "get_settings",
        lambda: SimpleNamespace(
            fal_key="test-key",
            max_fal_concurrency=4,
            MODEL_REGISTRY={
                "upscale": "fal-ai/clarity-upscaler",
                "outpaint": "fal-ai/flux-2-pro/outpaint",
                "i2v": "bytedance/seedance-2.0/image-to-video",
            },
        ),
    )


def _use_handler(monkeypatch, handler) -> dict:
    counter = {"n": 0}

    def wrapped(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return handler(request, counter["n"])

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    monkeypatch.setattr(fal, "get_client", lambda: client)
    return counter


async def test_retry_skips_4xx(monkeypatch):
    def handler(request, n):
        return httpx.Response(422, json={"detail": "bad args"})

    counter = _use_handler(monkeypatch, handler)
    with pytest.raises(fal.FalValidationError):
        await fal.run_upscale("https://example.com/a.jpg", 2)
    # 4xx must NOT be retried — exactly one request was made.
    assert counter["n"] == 1


async def test_transient_5xx_is_retried_then_succeeds(monkeypatch):
    submit = {
        "status": "IN_QUEUE",
        "request_id": "req1",
        "status_url": "https://queue.fal.run/m/requests/req1/status",
        "response_url": "https://queue.fal.run/m/requests/req1",
        "queue_position": 0,
    }

    def handler(request, n):
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(200, json=submit)
        if path.endswith("/status"):
            # First poll fails transiently, second completes.
            if n == 2:
                return httpx.Response(503, json={"detail": "busy"})
            return httpx.Response(200, json={"status": "COMPLETED", "request_id": "req1"})
        # response_url result
        return httpx.Response(200, json={"image": {"url": "https://cdn.fal/out.png"}})

    counter = _use_handler(monkeypatch, handler)
    result = await fal.run_upscale("https://example.com/a.jpg", 2)
    assert result == {"image": {"url": "https://cdn.fal/out.png"}}
    # POST(1) + status 503(2) + status COMPLETED(3) + result(4)
    assert counter["n"] == 4


async def test_happy_path_polls_until_completed(monkeypatch):
    submit = {
        "status": "IN_QUEUE",
        "request_id": "req9",
        "status_url": "https://queue.fal.run/m/requests/req9/status",
        "response_url": "https://queue.fal.run/m/requests/req9",
    }

    def handler(request, n):
        if request.method == "POST":
            return httpx.Response(200, json=submit)
        if request.url.path.endswith("/status"):
            status = "IN_PROGRESS" if n == 2 else "COMPLETED"
            return httpx.Response(200, json={"status": status, "request_id": "req9"})
        return httpx.Response(200, json={"video": {"url": "https://cdn.fal/clip.mp4"}})

    _use_handler(monkeypatch, handler)
    result = await fal.run_image_to_video(
        "https://example.com/a.jpg", "a cinematic walkthrough", 5, "16:9"
    )
    assert result["video"]["url"] == "https://cdn.fal/clip.mp4"


async def test_exhausts_retries_on_persistent_5xx(monkeypatch):
    def handler(request, n):
        return httpx.Response(500, json={"detail": "down"})

    counter = _use_handler(monkeypatch, handler)
    with pytest.raises(fal.FalTransientError):
        await fal.run_outpaint("https://example.com/a.jpg", 1920, 1080)
    # Submit retried up to _RETRY_ATTEMPTS times.
    assert counter["n"] == fal._RETRY_ATTEMPTS

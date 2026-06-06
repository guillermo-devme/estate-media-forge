"""WixRefundClient signs exactly as the Wix falRefund http-function verifies."""

from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

import app.providers.wix_client as wix

SECRET = "shared-hmac-secret"
SERVICE_KEY = "shared-service-key"
URL = "https://example.wixsite.com/_functions/falRefund"


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(wix, "_RETRY_MULTIPLIER", 0.0)
    monkeypatch.setattr(wix, "_RETRY_MAX", 0.0)


def _verify_like_wix(request: httpx.Request) -> None:
    """Reproduce post_falRefund's verification."""
    import json

    raw = request.content.decode()
    assert request.headers["x-service-key"] == SERVICE_KEY
    ts = request.headers["x-timestamp"]
    nonce = request.headers["x-nonce"]
    sig = request.headers["x-signature"]
    member_id = json.loads(raw)["member_id"]
    body_hash = hashlib.sha256(raw.encode()).hexdigest()
    expected = hmac.new(
        SECRET.encode(), f"{ts}.{nonce}.{member_id}.{body_hash}".encode(), hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(expected, sig), "signature must match Wix scheme"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_refund_signs_like_wix_and_returns_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        _verify_like_wix(request)
        import json

        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True, "refunded": 1122, "balance": 5000})

    refund_client = wix.WixRefundClient(
        refund_url=URL, service_key=SERVICE_KEY, hmac_secret=SECRET, client=_client(handler)
    )
    result = await refund_client.refund("mem_1", "job_1", 1122, "job_failed")
    assert result == {"ok": True, "refunded": 1122, "balance": 5000}
    assert captured["body"] == {
        "member_id": "mem_1",
        "job_id": "job_1",
        "refund_credits": 1122,
        "reason": "job_failed",
    }


async def test_refund_retries_transient_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"ok": True, "refunded": 20, "balance": 1})

    refund_client = wix.WixRefundClient(
        refund_url=URL, service_key=SERVICE_KEY, hmac_secret=SECRET, client=_client(handler)
    )
    result = await refund_client.refund("mem_1", "job_1", 20)
    assert result["ok"] is True
    assert calls["n"] == 2


async def test_refund_4xx_raises_loudly():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "signature mismatch"})

    refund_client = wix.WixRefundClient(
        refund_url=URL, service_key=SERVICE_KEY, hmac_secret=SECRET, client=_client(handler)
    )
    with pytest.raises(wix.WixRefundError):
        await refund_client.refund("mem_1", "job_1", 20)

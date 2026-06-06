"""Core router tests: signed 202 submit, auth rejection, ownership, idempotency."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.deps as deps
from app.deps import get_nonce_store
from app.jobs.store import JobStore
from app.main import create_app

SERVICE_KEY = "test-service-key"
HMAC_SECRET = "test-hmac-secret"


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def ping(self):
        return True


class MemoryNonceStore:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def claim(self, nonce: str) -> bool:
        if nonce in self.seen:
            return False
        self.seen.add(nonce)
        return True


class FakeUsage:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record_event(self, **kwargs):
        self.events.append(kwargs)


def _sign(body: bytes, member_id: str, *, ts=None, nonce=None) -> dict[str, str]:
    ts = ts or str(int(time.time()))
    nonce = nonce or str(uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{ts}.{nonce}.{member_id}.{body_hash}"
    signature = hmac.new(HMAC_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Service-Key": SERVICE_KEY,
        "X-Member-Id": member_id,
        "X-Member-Role": "member",
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: SimpleNamespace(
            service_key=SERVICE_KEY,
            service_hmac_secret=HMAC_SECRET,
            redis_url="redis://localhost:6379",
        ),
    )
    app = create_app()
    app.state.job_store = JobStore(client=FakeRedis())
    app.state.usage = FakeUsage()
    app.state.enqueue_calls = []

    async def fake_enqueue(service, job_id):
        app.state.enqueue_calls.append((service, job_id))

    app.state.enqueue = fake_enqueue
    app.dependency_overrides[get_nonce_store] = lambda: MemoryNonceStore()
    # No `with` → lifespan does not run (no real Redis/ARQ needed).
    return TestClient(app)


def _media_kit_body(member_id="mem_1", client_ref="spend_1", quoted=3366) -> bytes:
    return json.dumps(
        {
            "member_id": member_id,
            "client_ref": client_ref,
            "quoted_credits": quoted,
            "image_url": "https://example.com/a.jpg",
            "room_name": "kitchen",
            "aspect_ratios": ["1:1", "9:16", "16:9"],
        }
    ).encode()


def test_signed_media_kit_returns_202(client):
    body = _media_kit_body()
    resp = client.post("/v1/media-kit", content=body, headers=_sign(body, "mem_1"))
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "queued"
    assert data["service"] == "media_kit"
    assert data["quoted_credits"] == 3366
    assert data["poll_url"] == f"/v1/jobs/{data['job_id']}"
    assert client.app.state.enqueue_calls == [("media_kit", data["job_id"])]


def test_unsigned_request_is_401(client):
    body = _media_kit_body()
    resp = client.post("/v1/media-kit", content=body)  # no signature headers
    assert resp.status_code == 401


def test_tampered_body_is_401(client):
    body = _media_kit_body()
    headers = _sign(body, "mem_1")
    resp = client.post("/v1/media-kit", content=body + b" ", headers=headers)
    assert resp.status_code == 401


def test_get_job_enforces_ownership(client):
    body = _media_kit_body(member_id="mem_1", client_ref="own_1")
    created = client.post("/v1/media-kit", content=body, headers=_sign(body, "mem_1")).json()
    job_id = created["job_id"]

    # Owner can read.
    get_body = json.dumps({"member_id": "mem_1"}, separators=(",", ":")).encode()
    ok = client.get(f"/v1/jobs/{job_id}", headers=_sign(get_body, "mem_1"))
    assert ok.status_code == 200
    assert ok.json()["member_id"] == "mem_1"

    # A different member gets 404 (no enumeration).
    other_body = json.dumps({"member_id": "mem_2"}, separators=(",", ":")).encode()
    denied = client.get(f"/v1/jobs/{job_id}", headers=_sign(other_body, "mem_2"))
    assert denied.status_code == 404


def test_same_client_ref_is_idempotent(client):
    body = _media_kit_body(client_ref="spend_dup")

    first = client.post("/v1/media-kit", content=body, headers=_sign(body, "mem_1"))
    second = client.post("/v1/media-kit", content=body, headers=_sign(body, "mem_1"))

    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]

    # Only ONE job created and ONE enqueue.
    fake_redis = client.app.state.job_store.redis
    job_keys = [k for k in fake_redis.data if k.startswith("job:")]
    assert len(job_keys) == 1
    assert len(client.app.state.enqueue_calls) == 1


def test_by_client_ref_lookup(client):
    body = _media_kit_body(client_ref="lookup_1")
    created = client.post("/v1/media-kit", content=body, headers=_sign(body, "mem_1")).json()

    get_body = json.dumps({"member_id": "mem_1"}, separators=(",", ":")).encode()
    resp = client.get("/v1/jobs/by-client-ref/lookup_1", headers=_sign(get_body, "mem_1"))
    assert resp.status_code == 200
    assert resp.json()["job_id"] == created["job_id"]

    missing = client.get("/v1/jobs/by-client-ref/nope", headers=_sign(get_body, "mem_1"))
    assert missing.status_code == 404


def test_health_no_auth(client):
    assert client.get("/health").json() == {"status": "ok"}

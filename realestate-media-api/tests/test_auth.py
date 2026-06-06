"""HMAC service-auth tests mirroring the Velo falClient.js signing scheme."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.deps as deps
from app.deps import Auth, get_nonce_store

SERVICE_KEY = "test-service-key"
HMAC_SECRET = "test-hmac-secret"


class MemoryNonceStore:
    """In-memory nonce store (single-use) for tests."""

    def __init__(self) -> None:
        self.seen: set[str] = set()

    async def claim(self, nonce: str) -> bool:
        if nonce in self.seen:
            return False
        self.seen.add(nonce)
        return True


def _sign(
    *,
    body: bytes,
    signed_member_id: str,
    header_member_id: str | None = None,
    role: str = "member",
    service_key: str = SERVICE_KEY,
    secret: str = HMAC_SECRET,
    ts: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    ts = ts or str(int(time.time()))
    nonce = nonce or str(uuid4())
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{ts}.{nonce}.{signed_member_id}.{body_hash}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Service-Key": service_key,
        "X-Member-Id": header_member_id or signed_member_id,
        "X-Member-Role": role,
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

    api = FastAPI()

    store = MemoryNonceStore()

    @api.post("/protected")
    async def protected(auth: Auth):  # type: ignore[valid-type]
        return {"member_id": auth.member_id, "role": auth.role}

    @api.get("/protected-get")
    async def protected_get(auth: Auth):  # type: ignore[valid-type]
        return {"member_id": auth.member_id, "role": auth.role}

    api.dependency_overrides[get_nonce_store] = lambda: store  # shared instance
    return TestClient(api)


def _body(member_id: str) -> bytes:
    return json.dumps({"image_url": "https://x.com/a.jpg", "member_id": member_id}).encode()


def test_valid_signed_request_returns_auth_context(client):
    body = _body("mem_1")
    headers = _sign(body=body, signed_member_id="mem_1", role="pro")
    resp = client.post("/protected", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"member_id": "mem_1", "role": "pro"}


def test_tampered_body_is_rejected(client):
    body = _body("mem_1")
    headers = _sign(body=body, signed_member_id="mem_1")
    resp = client.post("/protected", content=body + b" ", headers=headers)
    assert resp.status_code == 401


def test_bad_service_key_is_rejected(client):
    body = _body("mem_1")
    headers = _sign(body=body, signed_member_id="mem_1", service_key="wrong-key")
    resp = client.post("/protected", content=body, headers=headers)
    assert resp.status_code == 401


def test_wrong_secret_signature_is_rejected(client):
    body = _body("mem_1")
    headers = _sign(body=body, signed_member_id="mem_1", secret="not-the-secret")
    resp = client.post("/protected", content=body, headers=headers)
    assert resp.status_code == 401


def test_reused_nonce_is_rejected(client):
    body = _body("mem_1")
    nonce = str(uuid4())
    headers = _sign(body=body, signed_member_id="mem_1", nonce=nonce)
    assert client.post("/protected", content=body, headers=headers).status_code == 200
    # Same nonce again (fresh signature/timestamp) → replay rejected.
    headers2 = _sign(body=body, signed_member_id="mem_1", nonce=nonce)
    assert client.post("/protected", content=body, headers=headers2).status_code == 401


def test_skewed_timestamp_is_rejected(client):
    body = _body("mem_1")
    old_ts = str(int(time.time()) - 400)
    headers = _sign(body=body, signed_member_id="mem_1", ts=old_ts)
    resp = client.post("/protected", content=body, headers=headers)
    assert resp.status_code == 401


def test_member_id_mismatch_is_rejected(client):
    # Body says mem_2, but the signed/header member is mem_1.
    body = _body("mem_2")
    headers = _sign(body=body, signed_member_id="mem_1", header_member_id="mem_1")
    resp = client.post("/protected", content=body, headers=headers)
    assert resp.status_code == 401


def test_empty_body_get_matches_canonical_member_body(client):
    # getFastApi signs over JSON.stringify({member_id}) but sends no body.
    signed_body = json.dumps({"member_id": "mem_1"}, separators=(",", ":")).encode()
    headers = _sign(body=signed_body, signed_member_id="mem_1")
    resp = client.get("/protected-get", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["member_id"] == "mem_1"

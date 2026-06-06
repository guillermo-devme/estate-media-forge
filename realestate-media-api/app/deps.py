"""Server-to-server auth: static service key + HMAC-signed body.

The only caller is the Wix Velo backend, which has already authenticated the
member and checked roles. This module verifies that a request genuinely came
from Wix and was not tampered with or replayed, then trusts the ``member_id`` it
carries.

Verification order (any failure → generic 401):

1. ``X-Service-Key`` matches ``settings.service_key`` (constant-time).
2. ``|now - X-Timestamp| <= 300s`` (bounds the replay window).
3. ``X-Nonce`` unseen — Redis ``SETNX`` with TTL 600s (blocks replay in-window).
4. ``X-Signature == HMAC_SHA256(secret,
   f"{ts}.{nonce}.{member_id}.{sha256_hex(raw_body)}")`` (constant-time).
5. ``X-Member-Id == body.member_id`` (the signed member is the spender).

NOTE: this is the static-key + HMAC model. Swapping to per-request signed JWTs
later (member claim replacing the static key) changes ONLY this dependency — no
endpoint signatures change.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.obs.logging import get_logger, member_id_var

_logger = get_logger("app.auth")

# Replay window for the signed timestamp, and how long nonces are remembered.
_MAX_SKEW_SECONDS = 300
_NONCE_TTL_SECONDS = 600

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Unauthorized",
    headers={"WWW-Authenticate": "HMAC"},
)


@dataclass(frozen=True)
class AuthContext:
    """The verified caller identity passed to routers."""

    member_id: str
    role: str


# ── Nonce store (replay protection) ────────────────────────────────────────────
class NonceStore(Protocol):
    """Claims a nonce exactly once. Returns True if unseen (claim succeeded)."""

    async def claim(self, nonce: str) -> bool: ...


class RedisNonceStore:
    """Redis-backed nonce store using ``SET key value NX EX``."""

    def __init__(self, client) -> None:  # noqa: ANN001 - redis.asyncio.Redis
        self._client = client

    async def claim(self, nonce: str) -> bool:
        # SET NX returns True when the key was set (nonce unseen), None otherwise.
        result = await self._client.set(f"nonce:{nonce}", "1", nx=True, ex=_NONCE_TTL_SECONDS)
        return bool(result)


_nonce_store: NonceStore | None = None


def get_nonce_store() -> NonceStore:
    """Return the process-wide Redis nonce store (lazily constructed)."""
    global _nonce_store
    if _nonce_store is None:
        import redis.asyncio as redis_asyncio

        client = redis_asyncio.from_url(get_settings().redis_url, decode_responses=True)
        _nonce_store = RedisNonceStore(client)
    return _nonce_store


# ── Crypto helpers ──────────────────────────────────────────────────────────────
def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expected_signature(secret: str, ts: str, nonce: str, member_id: str, body_hash: str) -> str:
    message = f"{ts}.{nonce}.{member_id}.{body_hash}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _canonical_member_body(member_id: str) -> bytes:
    """Reconstruct the body the Velo GET helper signs but does not send.

    ``getFastApi`` signs over ``JSON.stringify({member_id})`` while sending an
    empty HTTP body, so for empty-body requests we hash the same canonical
    single-key object. The member_id is itself part of the signed message and is
    validated, so reconstructing it adds no trust assumption.
    """
    return json.dumps({"member_id": member_id}, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _reject(reason: str) -> HTTPException:
    """Log the specific reason server-side; return a generic 401 to the caller."""
    _logger.warning("auth.reject", extra={"reason": reason})
    return _UNAUTHORIZED


async def _verify(
    request: Request,
    *,
    settings: Settings,
    nonce_store: NonceStore,
    now: float,
) -> AuthContext:
    headers = request.headers
    service_key = headers.get("X-Service-Key", "")
    member_id = headers.get("X-Member-Id", "")
    role = headers.get("X-Member-Role", "member") or "member"
    ts = headers.get("X-Timestamp", "")
    nonce = headers.get("X-Nonce", "")
    signature = headers.get("X-Signature", "")

    if not (member_id and ts and nonce and signature):
        raise _reject("missing_headers")

    # 1) Service key — only Wix can call us.
    if not (settings.service_key and hmac.compare_digest(service_key, settings.service_key)):
        raise _reject("service_key_mismatch")

    # 2) Timestamp skew — bound the replay window.
    try:
        ts_value = int(ts)
    except ValueError:
        raise _reject("timestamp_unparseable") from None
    if abs(now - ts_value) > _MAX_SKEW_SECONDS:
        raise _reject("timestamp_skew")

    # 3) Nonce — block replay within the window.
    if not await nonce_store.claim(nonce):
        raise _reject("nonce_replay")

    # 4) Signature over the raw body (or the canonical member body for empty GET).
    raw_body = await request.body()
    body_for_hash = raw_body if raw_body else _canonical_member_body(member_id)
    expected = _expected_signature(
        settings.service_hmac_secret, ts, nonce, member_id, _sha256_hex(body_for_hash)
    )
    if not hmac.compare_digest(signature, expected):
        raise _reject("signature_mismatch")

    # 5) Body member_id must match the signed header member_id (no spoofing).
    if raw_body:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            raise _reject("body_not_json") from None
        if not isinstance(payload, dict) or payload.get("member_id") != member_id:
            raise _reject("member_id_mismatch")

    # Bind identity into the logging context for correlated logs.
    member_id_var.set(member_id)
    return AuthContext(member_id=member_id, role=role)


async def verify_service_request(
    request: Request,
    nonce_store: Annotated[NonceStore, Depends(get_nonce_store)],
) -> AuthContext:
    """FastAPI dependency: verify the signed request and return the caller identity."""
    return await _verify(
        request,
        settings=get_settings(),
        nonce_store=nonce_store,
        now=time.time(),
    )


# Annotated alias for routers: `member: Auth`.
Auth = Annotated[AuthContext, Depends(verify_service_request)]

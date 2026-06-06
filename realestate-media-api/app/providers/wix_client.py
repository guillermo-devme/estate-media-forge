"""HMAC-signed client for the Wix refund callback (POST /_functions/falRefund).

Mirrors the inbound scheme: the worker signs ``{ts}.{nonce}.{member_id}.{sha256(body)}``
and sends X-Service-Key / X-Timestamp / X-Nonce / X-Signature. Wix enforces
idempotency on ``refund_{job_id}``, so retries can't double-refund. Refund
failures mean money is owed back to the member and MUST be logged loudly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

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

_logger = get_logger("app.wix")

_RETRY_ATTEMPTS = 3
_RETRY_MULTIPLIER = 0.5
_RETRY_MAX = 8.0


class WixRefundError(Exception):
    """Base error for the refund callback."""


class WixRefundTransientError(WixRefundError):
    """Retryable refund failure (network/timeout/5xx)."""


class WixRefundClient:
    """Posts proportional refunds back to the Wix falRefund http-function."""

    def __init__(
        self,
        *,
        refund_url: str | None = None,
        service_key: str | None = None,
        hmac_secret: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._url = refund_url or settings.wix_refund_url
        self._service_key = service_key or settings.service_key
        self._secret = hmac_secret or settings.service_hmac_secret
        self._client = client

    def _signed_headers(self, member_id: str, raw_body: str) -> dict[str, str]:
        ts = str(int(time.time()))
        nonce = str(uuid4())
        body_hash = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
        message = f"{ts}.{nonce}.{member_id}.{body_hash}"
        signature = hmac.new(
            self._secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Service-Key": self._service_key,
            "X-Timestamp": ts,
            "X-Nonce": nonce,
            "X-Signature": signature,
        }

    async def refund(
        self, member_id: str, job_id: str, credits: int, reason: str = "job_failed"
    ) -> dict:
        """POST a proportional refund. Idempotent Wix-side on refund_{job_id}."""
        async with span_ctx("wix.refund"):
            # Build the exact bytes we sign and send.
            raw_body = json.dumps(
                {
                    "member_id": member_id,
                    "job_id": job_id,
                    "refund_credits": credits,
                    "reason": reason,
                },
                separators=(",", ":"),
                ensure_ascii=False,
            )
            headers = self._signed_headers(member_id, raw_body)

            own_client = self._client is None
            client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(30.0))
            try:
                data = await self._post_with_retry(client, raw_body, headers)
            except Exception as exc:  # noqa: BLE001 - log loudly; money is owed back
                _logger.error(
                    "wix.refund_failed",
                    extra={
                        "member_id": member_id,
                        "job_id": job_id,
                        "refund_credits": credits,
                        "error": repr(exc),
                    },
                )
                raise
            finally:
                if own_client:
                    await client.aclose()

            _logger.info(
                "wix.refund_ok",
                extra={"member_id": member_id, "job_id": job_id, "refund_credits": credits},
            )
            return data

    async def _post_with_retry(
        self, client: httpx.AsyncClient, raw_body: str, headers: dict[str, str]
    ) -> dict:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(_RETRY_ATTEMPTS),
            wait=wait_random_exponential(multiplier=_RETRY_MULTIPLIER, max=_RETRY_MAX),
            retry=retry_if_exception_type(WixRefundTransientError),
            reraise=True,
        ):
            with attempt:
                return await self._post_once(client, raw_body, headers)
        raise WixRefundTransientError("unreachable")  # pragma: no cover

    async def _post_once(
        self, client: httpx.AsyncClient, raw_body: str, headers: dict[str, str]
    ) -> dict:
        try:
            response = await client.post(self._url, content=raw_body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise WixRefundTransientError(f"network error: {exc!r}") from exc
        if response.status_code >= 500:
            raise WixRefundTransientError(f"wix refund upstream {response.status_code}")
        if response.status_code >= 400:
            # 4xx: do not retry, but surface so the caller logs money-owed loudly.
            raise WixRefundError(f"wix refund rejected ({response.status_code})")
        return response.json()

"""Alert notifier — sends messages to a Google Chat webhook.

Used by the fal balance monitor to alert when provider credits run low.
"""

from __future__ import annotations

import httpx

from app.config import get_settings
from app.obs.logging import get_logger

_logger = get_logger("app.alerts")


async def send_google_chat_alert(message: str) -> bool:
    """POST a message to the configured Google Chat webhook. Returns True on success."""
    url = get_settings().google_chat_webhook_url
    if not url:
        _logger.warning("alerts.no_webhook_url", extra={"message": message})
        return False

    payload = {"text": message}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        _logger.info("alerts.sent", extra={"message": message[:100]})
        return True
    except Exception as exc:
        _logger.error("alerts.send_failed", extra={"error": repr(exc), "message": message[:100]})
        return False

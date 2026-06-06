"""fal.ai account balance monitor + circuit breaker.

Periodically checks the fal account balance via ``GET https://api.fal.ai/v1/account/billing``.
When the balance drops below the configured alert threshold ($20 default), sends a Google Chat
notification. When it drops to zero (or fal returns 402/payment errors), trips the circuit
breaker so new submit endpoints return 503 *before* decrementing the member's wallet.

The circuit breaker is a simple in-memory flag. A dedicated GPU migration removes it entirely.

State machine:
```
  CLOSED (healthy)
    │ fal balance < alert_threshold
    ▼
  CLOSED + alert sent (once per low-balance episode)
    │ fal balance == 0 OR fal 402 errors observed
    ▼
  OPEN (tripped)
    │ submit endpoints → 503 "Provider capacity exhausted"
    │ periodic check: fal balance > 0 again?
    ▼
  CLOSED (auto-recovery)
```
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.obs.logging import get_logger
from app.providers.alerts import send_google_chat_alert

_logger = get_logger("app.fal_balance")

FAL_BILLING_URL = "https://api.fal.ai/v1/account/billing"


@dataclass
class CircuitState:
    """In-memory circuit breaker state for fal provider capacity."""

    is_open: bool = False
    last_balance_usd: float | None = None
    last_check: datetime | None = None
    alert_sent_for_episode: bool = False
    consecutive_402s: int = 0
    # Track to avoid spamming (one alert per low-balance episode).
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Process-global state (shared by the API process; worker has its own instance).
circuit = CircuitState()


async def check_fal_balance() -> float | None:
    """Fetch the fal account balance in USD. Returns None on failure."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(
                FAL_BILLING_URL,
                params={"expand": "credits"},
                headers={"Authorization": f"Key {settings.fal_key}"},
            )
            if response.status_code == 401:
                _logger.error("fal_balance.auth_failed")
                return None
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        _logger.warning("fal_balance.fetch_failed", extra={"error": repr(exc)})
        return None

    # Parse balance from the response — exact shape may vary; try common paths.
    balance = (
        data.get("balance")
        or data.get("credits_remaining")
        or data.get("credits", {}).get("balance")
        or data.get("credits", {}).get("remaining")
    )
    if balance is None:
        # Last resort: look for any numeric field that looks like a balance.
        for key in ("balance", "remaining", "available", "credits_remaining"):
            if key in data and isinstance(data[key], (int, float)):
                balance = data[key]
                break
    if balance is None:
        _logger.warning("fal_balance.unknown_shape", extra={"keys": list(data.keys())})
        return None

    return float(balance)


async def run_balance_check() -> dict:
    """The periodic check: fetch balance, alert if low, trip/recover circuit breaker.

    Returns a status dict for logging/metrics.
    """
    settings = get_settings()
    threshold = settings.fal_balance_alert_threshold_usd

    balance = await check_fal_balance()
    now = datetime.now(timezone.utc)

    async with circuit._lock:
        circuit.last_check = now

        if balance is None:
            # Can't determine balance — don't change state; log and move on.
            return {"status": "unknown", "balance": None, "circuit": "unchanged"}

        circuit.last_balance_usd = balance

        # ── Recovery: balance is back above zero → close the circuit.
        if balance > 0 and circuit.is_open:
            circuit.is_open = False
            circuit.consecutive_402s = 0
            _logger.info("fal_balance.circuit_closed", extra={"balance": balance})
            await send_google_chat_alert(
                f"✅ fal.ai balance recovered: ${balance:.2f}. Circuit breaker closed, submissions re-enabled."
            )
            circuit.alert_sent_for_episode = False
            return {"status": "recovered", "balance": balance, "circuit": "closed"}

        # ── Critical: balance is zero (or negative) → trip the circuit.
        if balance <= 0:
            if not circuit.is_open:
                circuit.is_open = True
                _logger.error("fal_balance.circuit_open", extra={"balance": balance})
                await send_google_chat_alert(
                    f"🚨 fal.ai balance is ${balance:.2f} — CIRCUIT BREAKER TRIPPED. "
                    f"New submissions will be rejected (503) until balance is topped up."
                )
            return {"status": "critical", "balance": balance, "circuit": "open"}

        # ── Low balance: alert but don't trip yet.
        if balance < threshold:
            if not circuit.alert_sent_for_episode:
                circuit.alert_sent_for_episode = True
                _logger.warning(
                    "fal_balance.low", extra={"balance": balance, "threshold": threshold}
                )
                await send_google_chat_alert(
                    f"⚠️ fal.ai balance is LOW: ${balance:.2f} (threshold: ${threshold:.2f}). "
                    f"Top up soon to avoid service interruption. "
                    f"At current rates this covers ~{int(balance / 0.68)} seconds of video or "
                    f"~{int(balance / 3.5)} full media kits."
                )
            return {"status": "low", "balance": balance, "circuit": "closed"}

        # ── Healthy
        if circuit.alert_sent_for_episode and balance >= threshold:
            circuit.alert_sent_for_episode = False  # reset for next episode
        return {"status": "healthy", "balance": balance, "circuit": "closed"}


def trip_on_402() -> None:
    """Called by the fal client when a 402 (payment required) is received.

    After N consecutive 402s, trip the circuit even between periodic checks.
    """
    circuit.consecutive_402s += 1
    if circuit.consecutive_402s >= 3 and not circuit.is_open:
        circuit.is_open = True
        _logger.error(
            "fal_balance.circuit_open_via_402",
            extra={"consecutive_402s": circuit.consecutive_402s},
        )
        # Fire-and-forget alert (we're likely in a sync context in the error handler).
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                send_google_chat_alert(
                    "🚨 fal.ai returning 402 (payment required) — CIRCUIT BREAKER TRIPPED via live errors. "
                    "Top up immediately."
                )
            )
        except RuntimeError:
            pass  # no event loop; the periodic check will catch it next cycle


def is_circuit_open() -> bool:
    """Check if the circuit breaker is currently tripped (provider capacity exhausted)."""
    return circuit.is_open

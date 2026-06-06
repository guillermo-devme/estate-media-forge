"""fal balance monitor: alerts, circuit breaker, 402 trip, recovery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.providers.fal_balance import (
    circuit,
    is_circuit_open,
    run_balance_check,
    trip_on_402,
)


@pytest.fixture(autouse=True)
def reset_circuit():
    """Reset the global circuit state before each test."""
    circuit.is_open = False
    circuit.last_balance_usd = None
    circuit.last_check = None
    circuit.alert_sent_for_episode = False
    circuit.consecutive_402s = 0
    yield
    circuit.is_open = False
    circuit.last_balance_usd = None
    circuit.alert_sent_for_episode = False
    circuit.consecutive_402s = 0


@pytest.fixture
def mock_settings(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.providers.fal_balance.get_settings",
        lambda: SimpleNamespace(
            fal_key="test-key",
            fal_balance_alert_threshold_usd=20.0,
            google_chat_webhook_url="https://chat.example.com/hook",
        ),
    )


@patch("app.providers.fal_balance.check_fal_balance")
@patch("app.providers.fal_balance.send_google_chat_alert", new_callable=AsyncMock)
async def test_low_balance_sends_alert_once(mock_alert, mock_check, mock_settings):
    mock_check.return_value = 15.0  # below $20 threshold
    result = await run_balance_check()
    assert result["status"] == "low"
    assert result["circuit"] == "closed"
    mock_alert.assert_called_once()
    assert "LOW" in mock_alert.call_args[0][0]

    # Second check: still low, but alert not re-sent (once per episode).
    mock_alert.reset_mock()
    result = await run_balance_check()
    assert result["status"] == "low"
    mock_alert.assert_not_called()


@patch("app.providers.fal_balance.check_fal_balance")
@patch("app.providers.fal_balance.send_google_chat_alert", new_callable=AsyncMock)
async def test_zero_balance_trips_circuit(mock_alert, mock_check, mock_settings):
    mock_check.return_value = 0.0
    result = await run_balance_check()
    assert result["status"] == "critical"
    assert result["circuit"] == "open"
    assert is_circuit_open() is True
    assert "CIRCUIT BREAKER TRIPPED" in mock_alert.call_args[0][0]


@patch("app.providers.fal_balance.check_fal_balance")
@patch("app.providers.fal_balance.send_google_chat_alert", new_callable=AsyncMock)
async def test_recovery_closes_circuit(mock_alert, mock_check, mock_settings):
    circuit.is_open = True  # simulate previously tripped
    mock_check.return_value = 50.0  # healthy again
    result = await run_balance_check()
    assert result["status"] == "recovered"
    assert result["circuit"] == "closed"
    assert is_circuit_open() is False
    assert "recovered" in mock_alert.call_args[0][0]


@patch("app.providers.fal_balance.check_fal_balance")
@patch("app.providers.fal_balance.send_google_chat_alert", new_callable=AsyncMock)
async def test_healthy_balance_no_alert(mock_alert, mock_check, mock_settings):
    mock_check.return_value = 100.0
    result = await run_balance_check()
    assert result["status"] == "healthy"
    assert result["circuit"] == "closed"
    mock_alert.assert_not_called()


def test_trip_on_402_trips_after_threshold():
    assert not is_circuit_open()
    trip_on_402()
    trip_on_402()
    assert not is_circuit_open()  # needs 3
    trip_on_402()
    assert is_circuit_open()

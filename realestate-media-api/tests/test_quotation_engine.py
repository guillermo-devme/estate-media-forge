"""Quotation engine: pure pricing, no balance/USD, refunds reconcile exactly."""

from __future__ import annotations

import pytest

from app import pricing
from app.schemas.enums import ServiceType
from app.wallet.quotation import QuotationEngine, ratio_credits


def _iter_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _iter_keys(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_keys(item)


@pytest.fixture
def engine() -> QuotationEngine:
    return QuotationEngine()


def test_ratio_credits_is_the_pricing_function():
    # Re-exported, not re-implemented.
    assert ratio_credits is pricing.ratio_credits


async def test_media_kit_total_reconciles_to_sum_of_ratio_credits(engine):
    ratios = ["1:1", "9:16", "16:9"]
    params = {"aspect_ratios": ratios, "duration_seconds": 5, "do_expand": True, "room_name": "den"}
    result = await engine.estimate(ServiceType.MEDIA_KIT, params)
    expected = sum(
        ratio_credits(ServiceType.MEDIA_KIT, r, duration_seconds=5, do_expand=True) for r in ratios
    )
    assert result["total_credits"] == expected
    assert result["service"] == "media_kit"


async def test_image_to_video_total_reconciles_to_sum_of_ratio_credits(engine):
    ratios = ["1:1", "9:16", "16:9"]
    params = {"aspect_ratios": ratios, "duration_seconds": 5, "room_name": "patio"}
    result = await engine.estimate(ServiceType.IMAGE_TO_VIDEO, params)
    expected = sum(ratio_credits(ServiceType.IMAGE_TO_VIDEO, r, duration_seconds=5) for r in ratios)
    assert result["total_credits"] == expected


async def test_estimate_has_no_usd_or_balance_fields(engine):
    params = {"aspect_ratios": ["1:1", "9:16", "16:9"], "room_name": "loft"}
    result = await engine.estimate(ServiceType.MEDIA_KIT, params)
    forbidden = ("usd", "price", "cost", "dollar", "balance", "available")
    for key in _iter_keys(result):
        assert not any(tok in str(key).lower() for tok in forbidden), key
    # breakdown items are per-stage {stage, quantity, credits}
    assert {k for item in result["breakdown"] for k in item} == {"stage", "quantity", "credits"}


async def test_room_name_required_for_video_and_media_kit(engine):
    with pytest.raises(ValueError, match="room_name"):
        await engine.estimate(ServiceType.MEDIA_KIT, {"aspect_ratios": ["1:1"]})
    with pytest.raises(ValueError, match="room_name"):
        await engine.estimate(ServiceType.IMAGE_TO_VIDEO, {"aspect_ratios": ["1:1"]})
    # upscale does not require room_name
    out = await engine.estimate(ServiceType.UPSCALE, {"aspect_ratios": ["1:1"]})
    assert out["total_credits"] > 0


async def test_unknown_ratio_is_rejected(engine):
    with pytest.raises(ValueError, match="unknown aspect ratio"):
        await engine.estimate(ServiceType.UPSCALE, {"aspect_ratios": ["4:3"]})


async def test_allowance_zero_yields_zeros(engine):
    result = await engine.allowance(0)
    assert result == {"allowance": {"upscale_images": 0, "videos_8s": 0, "media_kits": 0}}


async def test_engine_ratio_credits_delegates(engine):
    direct = ratio_credits(ServiceType.MEDIA_KIT, "1:1", duration_seconds=5, do_expand=True)
    via_engine = await engine.ratio_credits(
        ServiceType.MEDIA_KIT, "1:1", {"duration_seconds": 5, "do_expand": True}
    )
    assert via_engine == direct

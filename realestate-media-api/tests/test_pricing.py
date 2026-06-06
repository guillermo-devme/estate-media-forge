"""Pricing math tests — credits only, refunds must reconcile, no USD leaks."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.pricing import (
    DEFAULT_RATIOS,
    Service,
    allowance,
    apply_margin,
    quote_credits,
    raw_cost_usd,
    ratio_credits,
    usd_to_credits,
)
from app.pricing import FalStage


def _iter_keys(obj):
    """Yield every dict key found anywhere in a nested structure."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _iter_keys(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_keys(item)


def test_media_kit_quote_expected_integer_credits():
    # Defaults: upscale=0.06, outpaint=0.045, i2v=0.68, ratio=3.2, peg=0.01.
    # per ratio raw = 0.06 + 0.045 + 0.68*5 = 3.505
    #          price = 3.505 * 3.2 = 11.216 -> ceil(1121.6) = 1122 credits
    # total over 3 ratios = 3366
    quote = quote_credits(Service.MEDIA_KIT)
    assert quote["total_credits"] == 3366
    assert isinstance(quote["total_credits"], int)
    assert all(entry["credits"] == 1122 for entry in quote["breakdown"])


def test_total_credits_reconciles_to_sum_of_ratio_credits():
    # MANDATORY: the total must equal the sum of the per-ratio canonical units,
    # so partial/total refunds always reconcile to the original charge.
    quote = quote_credits(Service.MEDIA_KIT, ratios=DEFAULT_RATIOS, duration_seconds=5)
    expected = sum(ratio_credits(Service.MEDIA_KIT, r) for r in DEFAULT_RATIOS)
    assert quote["total_credits"] == expected


def test_no_usd_anywhere_in_returned_dicts():
    forbidden = ("usd", "price", "cost", "dollar", "$")
    for result in (
        quote_credits(Service.MEDIA_KIT),
        quote_credits(Service.UPSCALE, ratios=(), images=3),
        quote_credits(Service.IMAGE_TO_VIDEO),
        allowance(10_000),
    ):
        for key in _iter_keys(result):
            assert not any(token in str(key).lower() for token in forbidden), key


def test_ratio_credits_is_atomic_per_ratio():
    # image_to_video for 8s at defaults: 0.68*8=5.44 *3.2=17.408 -> ceil(1740.8)=1741
    assert ratio_credits(Service.IMAGE_TO_VIDEO, "16:9", duration_seconds=8) == 1741
    # upscale single image: 0.06*3.2=0.192 -> ceil(19.2)=20
    assert ratio_credits(Service.UPSCALE, "1:1") == 20


def test_do_expand_false_drops_outpaint():
    with_expand = ratio_credits(Service.MEDIA_KIT, "1:1", do_expand=True)
    without_expand = ratio_credits(Service.MEDIA_KIT, "1:1", do_expand=False)
    assert without_expand < with_expand


def test_ratioless_upscale_sums_per_image():
    quote = quote_credits(Service.UPSCALE, ratios=(), images=3)
    assert len(quote["breakdown"]) == 3
    assert quote["total_credits"] == 3 * ratio_credits(Service.UPSCALE)


def test_pure_money_primitives():
    raw = raw_cost_usd([(FalStage.I2V, 5)])
    assert raw == Decimal("3.40")
    assert apply_margin(raw) == Decimal("10.880")
    assert usd_to_credits(Decimal("11.216")) == 1122


def test_allowance_is_integer_and_nonnegative():
    result = allowance(10_000)
    assert all(isinstance(v, int) and v >= 0 for v in result.values())
    # 10000 // 20 upscale-images
    assert result["upscale_images"] == 10_000 // ratio_credits(Service.UPSCALE, "1:1")


if __name__ == "__main__":
    import json

    print(json.dumps(quote_credits(Service.MEDIA_KIT), indent=2))
    pytest.main([__file__, "-v"])

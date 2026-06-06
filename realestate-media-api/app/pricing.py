"""Pricing & token economy — pure, deterministic, no I/O.

USD math lives **only** in this module and never leaves the server. Every value
returned to a caller is expressed in integer **credits**; no USD/cost field is
ever serialized.

Pipeline::

    raw_cost_usd = Σ(stage_unit_cost × stage_quantity)
    price_usd    = raw_cost_usd × earnings_ratio          (INTERNAL ONLY)
    credits      = ceil(price_usd ÷ credit_peg_usd)

The ceil is applied at the **per-ratio** grain (``ratio_credits``) so that the
per-ratio amount is the atomic, refundable unit and::

    quote_credits(...).total_credits == Σ ratio_credits(each requested ratio)

holds exactly — refunds always reconcile to the original charge.

Cost table provenance (verified against live fal.ai model pages, 2026-06-05):

* upscale  — ``fal-ai/clarity-upscaler``: **$0.03 / megapixel** of output.
* outpaint — ``fal-ai/flux-2-pro/outpaint``: **$0.03 first MP + $0.015 / extra MP**.
* i2v      — ``bytedance/seedance-2.0/image-to-video``: **$0.3034/s @720p,
  $0.682/s @ true-1080p**.

fal bills the image stages per-megapixel, but this module's cost model is
per-image / per-second (the line-item quantity drivers are images and seconds).
The committed per-image defaults below are therefore *representative averages*
derived from the verified per-MP rates assuming ~2 MP outputs; i2v uses the
true-1080p per-second rate because RATIO_DIMS produce 1080p frames. All values
are overridable via the ``PRICING_JSON`` env var so ops can correct them without
a code change.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from functools import lru_cache

from app.config import get_settings
from app.schemas.enums import FalStage
from app.schemas.enums import ServiceType as Service

# ``Service`` is an alias of the canonical ``ServiceType`` enum (app.schemas.enums),
# kept for the pricing-domain naming used throughout this module and its tests.
__all__ = [
    "FalStage",
    "Service",
    "COST_TABLE",
    "DEFAULT_COST_USD",
    "DEFAULT_RATIOS",
    "get_cost_table",
    "raw_cost_usd",
    "apply_margin",
    "usd_to_credits",
    "ratio_credits",
    "quote_credits",
    "allowance",
]


# Representative per-unit provider cost in USD. Derived from verified fal pricing
# (see module docstring); per-image stages assume ~2 MP outputs.
DEFAULT_COST_USD: dict[FalStage, Decimal] = {
    # ~2 MP × $0.03/MP (clarity-upscaler, verified per-MP rate, 2026-06-05).
    FalStage.UPSCALE: Decimal("0.06"),
    # flux-2-pro: $0.03 first MP + $0.015 extra MP ≈ 2 MP output (verified 2026-06-05).
    FalStage.OUTPAINT: Decimal("0.045"),
    # seedance-2.0 true-1080p $0.682/s (720p tier = $0.3034/s) (verified 2026-06-05).
    FalStage.I2V: Decimal("0.68"),
}


@lru_cache
def get_cost_table() -> dict[FalStage, Decimal]:
    """Return the provider cost table, merging any ``PRICING_JSON`` override.

    ``PRICING_JSON`` is an object keyed by stage value, e.g.
    ``{"upscale": 0.06, "outpaint": 0.045, "i2v": 0.68}``.
    """
    table = dict(DEFAULT_COST_USD)
    raw = get_settings().pricing_json
    if raw:
        overrides = json.loads(raw)
        for key, value in overrides.items():
            table[FalStage(key)] = Decimal(str(value))
    return table


# Module-level convenience snapshot (built from defaults + env at import time).
COST_TABLE: dict[FalStage, Decimal] = get_cost_table()


# ──────────────────────────────────────────────────────────────────────────────
# Pure money primitives (USD — never serialized)
# ──────────────────────────────────────────────────────────────────────────────
def raw_cost_usd(line_items: list[tuple[FalStage, int]]) -> Decimal:
    """Sum provider USD cost over ``(stage, quantity)`` line items."""
    table = get_cost_table()
    total = Decimal("0")
    for stage, quantity in line_items:
        total += table[FalStage(stage)] * Decimal(quantity)
    return total


def apply_margin(raw_usd: Decimal) -> Decimal:
    """Apply the earnings ratio to a raw provider cost → internal price (USD)."""
    ratio = Decimal(str(get_settings().earnings_ratio))
    return raw_usd * ratio


def usd_to_credits(price_usd: Decimal) -> int:
    """Convert an internal USD price to integer credits via ``ceil(price / peg)``."""
    peg = Decimal(str(get_settings().credit_peg_usd))
    return math.ceil(price_usd / peg)


def _line_items(
    service: Service,
    *,
    duration_seconds: int,
    do_expand: bool,
) -> list[tuple[FalStage, int]]:
    """Stage line items for ONE aspect ratio of a service."""
    if service is Service.UPSCALE:
        return [(FalStage.UPSCALE, 1)]
    if service is Service.IMAGE_TO_VIDEO:
        return [(FalStage.I2V, duration_seconds)]
    # media_kit: upscale + (optional outpaint) + i2v
    items: list[tuple[FalStage, int]] = [(FalStage.UPSCALE, 1)]
    if do_expand:
        items.append((FalStage.OUTPAINT, 1))
    items.append((FalStage.I2V, duration_seconds))
    return items


def ratio_credits(
    service: Service | str,
    ratio: str | None = None,
    *,
    duration_seconds: int = 5,
    do_expand: bool = True,
    upscale_factor: int = 2,
) -> int:
    """Credits for ONE aspect ratio of ``service`` — the canonical refundable unit.

    The ceil is applied here, at the per-ratio grain, so this is the exact amount
    the worker refunds per failed ratio (prompt 12) and quotation re-exports
    (prompt 08). ``ratio``/``upscale_factor`` are part of the contract but do not
    change the per-image cost in this simplified model.
    """
    svc = Service(service)
    items = _line_items(svc, duration_seconds=duration_seconds, do_expand=do_expand)
    return usd_to_credits(apply_margin(raw_cost_usd(items)))


DEFAULT_RATIOS: tuple[str, ...] = ("1:1", "9:16", "16:9")


def quote_credits(
    service: Service | str,
    *,
    images: int = 1,
    ratios: tuple[str, ...] = DEFAULT_RATIOS,
    duration_seconds: int = 5,
    do_expand: bool = True,
    upscale_factor: int = 2,
) -> dict:
    """Quote a service in credits only, with a per-ratio breakdown.

    ``total_credits`` is the EXACT SUM of the per-ratio canonical units (not a
    separate ceil over a combined USD total), guaranteeing refunds reconcile::

        total_credits == Σ ratio_credits(each requested ratio)
    """
    svc = Service(service)
    breakdown: list[dict] = []
    stage_counts: dict[str, int] = {}

    def _record(items: list[tuple[FalStage, int]]) -> None:
        for stage, _qty in items:
            stage_counts[stage.value] = stage_counts.get(stage.value, 0) + 1

    if svc is Service.UPSCALE and not ratios:
        # Ratio-less upscale: each requested image is one unit.
        unit = ratio_credits(svc, None, upscale_factor=upscale_factor)
        for index in range(max(images, 1)):
            breakdown.append({"ratio": f"image_{index + 1}", "credits": unit})
            _record(_line_items(svc, duration_seconds=duration_seconds, do_expand=do_expand))
    else:
        for ratio in ratios:
            credits = ratio_credits(
                svc,
                ratio,
                duration_seconds=duration_seconds,
                do_expand=do_expand,
                upscale_factor=upscale_factor,
            )
            breakdown.append({"ratio": ratio, "credits": credits})
            _record(_line_items(svc, duration_seconds=duration_seconds, do_expand=do_expand))

    total_credits = sum(entry["credits"] for entry in breakdown)
    return {
        "service": svc.value,
        "ratios": list(ratios),
        "duration_seconds": duration_seconds,
        "breakdown": breakdown,
        "stage_counts": stage_counts,
        "total_credits": total_credits,
    }


def allowance(balance_credits: int) -> dict:
    """How many of each service a credit balance buys (same per-ratio sums)."""
    upscale_unit = ratio_credits(Service.UPSCALE, "1:1")
    video_unit = ratio_credits(Service.IMAGE_TO_VIDEO, "16:9", duration_seconds=8)
    media_kit_unit = quote_credits(Service.MEDIA_KIT, ratios=DEFAULT_RATIOS, duration_seconds=5)[
        "total_credits"
    ]

    def _buys(unit: int) -> int:
        return balance_credits // unit if unit > 0 else 0

    return {
        "upscale_images": _buys(upscale_unit),
        "videos_8s": _buys(video_unit),
        "media_kits": _buys(media_kit_unit),
    }

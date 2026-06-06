"""Quotation / pricing engine — credits only, NO balance check.

Balance lives in Wix CMS, so this engine never checks affordability. Given a
service + params it returns ``{service, total_credits, breakdown}``; Wix compares
``total_credits`` to the member's CMS balance and decides.

``ratio_credits`` is re-exported from :mod:`app.pricing` (prompt 03) so the worker
imports the ONE canonical per-ratio unit it refunds — the rounding is never
re-implemented here.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from app import pricing
from app.obs.spans import span
from app.schemas.enums import AspectRatio, FalStage, ServiceType

# Re-export THE canonical per-ratio unit (single definition for the worker).
ratio_credits = pricing.ratio_credits

_ROOM_REQUIRED = (ServiceType.IMAGE_TO_VIDEO, ServiceType.MEDIA_KIT)


def _ratio_value(ratio: Enum | str) -> str:
    return ratio.value if isinstance(ratio, Enum) else str(ratio)


class QuotationEngine:
    """Pure pricing service. Holds no repository, balance, or affordability logic."""

    @span("quotation.estimate")
    async def estimate(self, service: ServiceType | str, params: Mapping[str, Any]) -> dict:
        """Return a credits quote with a per-stage breakdown. No balance/USD."""
        svc = ServiceType(service)

        room_name = params.get("room_name")
        if svc in _ROOM_REQUIRED and not room_name:
            raise ValueError(f"room_name is required for service '{svc.value}'")

        # Normalize + validate ratios (reject unknown aspect ratios).
        raw_ratios = params.get("aspect_ratios")
        if raw_ratios is None:
            ratios = pricing.DEFAULT_RATIOS
        else:
            ratios = tuple(self._validate_ratio(r) for r in raw_ratios)

        duration_seconds = int(params.get("duration_seconds", 5))
        do_expand = bool(params.get("do_expand", True))
        upscale_factor = int(params.get("upscale_factor", 2))
        images = int(params.get("images", 1))

        quote = pricing.quote_credits(
            svc,
            images=images,
            ratios=ratios,
            duration_seconds=duration_seconds,
            do_expand=do_expand,
            upscale_factor=upscale_factor,
        )

        ratio_count = images if (svc is ServiceType.UPSCALE and not ratios) else len(ratios)
        breakdown = self._stage_breakdown(svc, ratio_count, duration_seconds, do_expand)

        return {
            "service": svc.value,
            "total_credits": quote["total_credits"],
            "breakdown": breakdown,
        }

    @span("quotation.allowance")
    async def allowance(self, balance: int) -> dict:
        """How many of each service a Wix-provided credit balance buys."""
        return {"allowance": pricing.allowance(balance)}

    @span("quotation.ratio_credits")
    async def ratio_credits(
        self, service: ServiceType | str, ratio: str, params: Mapping[str, Any] | None = None
    ) -> int:
        """Delegate to the canonical pricing.ratio_credits (the worker's refund unit)."""
        params = params or {}
        return pricing.ratio_credits(
            service,
            ratio,
            duration_seconds=int(params.get("duration_seconds", 5)),
            do_expand=bool(params.get("do_expand", True)),
            upscale_factor=int(params.get("upscale_factor", 2)),
        )

    @staticmethod
    def _validate_ratio(ratio: Enum | str) -> str:
        value = _ratio_value(ratio)
        try:
            return AspectRatio(value).value
        except ValueError as exc:
            raise ValueError(f"unknown aspect ratio: {value!r}") from exc

    @staticmethod
    def _stage_breakdown(
        service: ServiceType, ratio_count: int, duration_seconds: int, do_expand: bool
    ) -> list[dict]:
        """Per-stage informational rollup (credits via pricing primitives, no USD).

        The authoritative number is total_credits (the per-ratio sum); this
        breakdown is for display.
        """
        if service is ServiceType.UPSCALE:
            line_items = [(FalStage.UPSCALE, ratio_count)]
        elif service is ServiceType.IMAGE_TO_VIDEO:
            line_items = [(FalStage.I2V, duration_seconds * ratio_count)]
        else:  # media_kit
            line_items = [(FalStage.UPSCALE, ratio_count)]
            if do_expand:
                line_items.append((FalStage.OUTPAINT, ratio_count))
            line_items.append((FalStage.I2V, duration_seconds * ratio_count))

        breakdown: list[dict] = []
        for stage, quantity in line_items:
            credits = pricing.usd_to_credits(
                pricing.apply_margin(pricing.raw_cost_usd([(stage, quantity)]))
            )
            breakdown.append({"stage": stage.value, "quantity": quantity, "credits": credits})
        return breakdown

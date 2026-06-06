# 03 — Pricing & Token Economy (cost table · 3.2x · credit peg)

This is the heart of quotation. USD math lives **only** here and never leaves the server —
responses speak **credits**.

## Cost → credits pipeline (pure functions, no I/O)

```
 COST TABLE (per stage, per model)            quantity drivers
 ┌──────────────────────────────┐            ┌───────────────────────────┐
 │ upscale  : $0.003 / image     │            │ media_kit = 3 ratios       │
 │ outpaint : $0.004 / image     │            │   × (upscale+outpaint+i2v) │
 │ i2v      : $0.010 / sec        │            │ upscale  = N images        │
 └──────────────┬───────────────┘            │ i2v      = duration_seconds│
                │                             └───────────────────────────┘
                ▼
   raw_cost_usd = Σ(stage_unit_cost × stage_quantity)
                │
                │  × earnings_ratio (3.2)        ← margin
                ▼
   price_usd  (INTERNAL ONLY, never serialized to client)
                │  ÷ credit_peg_usd ($0.01)
                ▼
   credits_float ── math.ceil ──▶ credits (int)   ← the only number the user sees
```

## Per-service price (used for the "what your balance buys" allowance view)

```
 price_credits(upscale, 1 img)        ─┐
 price_credits(i2v, 8s)               ─┤─▶ allowance = balance ÷ price_per_service
 price_credits(media_kit, 1 img, 5s)  ─┘     ⇒ {upscale: 50, video_8s: 5, media_kit: 6}
```

## Prompt

```
Implement app/pricing.py — pure, deterministic, no I/O. Read earnings_ratio and credit_peg_usd
from settings.

1) COST_TABLE: dict[FalStage, dict] giving provider average USD cost. Defaults (override via env
   PRICING_JSON): upscale = 0.003 per image, outpaint = 0.004 per image, i2v = 0.010 per second.
   ⚠️ HARD GATE — these numbers are UNVERIFIED placeholders. Before relying on them, confirm each
   against real fal.ai pricing (the model pages / a real fal invoice). Wrong costs ⇒ wrong margin
   and wrong credit prices for every job. Mark any unconfirmed value with a
   `# UNVERIFIED: confirm against fal pricing` comment. They are env-overridable via PRICING_JSON so
   ops can correct them without a code change, but the committed defaults must be checked.

2) raw_cost_usd(line_items: list[(stage, quantity)]) -> Decimal. Use Decimal for money.

3) apply_margin(raw_usd) -> price_usd = raw_usd * earnings_ratio.

4) usd_to_credits(price_usd) -> int via math.ceil(price_usd / credit_peg_usd).

5) **ratio_credits(service, ratio, *, duration_seconds=5, do_expand=True, upscale_factor=2) -> int**
   — THE canonical priced unit. Credits for ONE aspect ratio of a service, with the ceil applied
   HERE (at the per-ratio grain), so it is the atomic, refundable amount:
     - upscale         : upscale × 1                      (one upscaled image for this ratio)
     - image_to_video  : i2v × duration_seconds           (one clip for this ratio)
     - media_kit       : upscale×1 + (outpaint×1 if do_expand) + i2v×duration_seconds
   Compute raw_cost → apply_margin → usd_to_credits (ceil) and return the int. Export it — the
   worker (prompt 12) refunds EXACTLY this per failed ratio, and quotation (prompt 08) re-exports it.

6) quote_credits(service, *, images=1, ratios=("1:1","9:16","16:9"), duration_seconds=5,
   do_expand=True, upscale_factor=2) -> dict with breakdown + total_credits (int).
   CRITICAL — to guarantee refunds reconcile to the charge, the total is the EXACT SUM of the
   per-ratio canonical units, NOT a separate ceil over a combined USD total:
       total_credits = Σ over `ratios` of ratio_credits(service, r, ...)
   (For the `upscale` service `ratios` is the requested aspect_ratios list, one upscaled image each;
   if a caller passes `images` for a ratio-less upscale, treat each image as one unit and sum those.)
   Because ceil(Σ per-ratio) is replaced by Σ ceil(per-ratio), the invariant
       quoted_credits == Σ ratio_credits(all requested ratios)
   holds exactly, so on total failure the full refund equals the charge and on partial failure the
   refunded ratios + kept ratios sum back to the original charge — never over- or under-refunding.
   breakdown = list of {ratio, credits} (one entry per ratio) plus an optional per-stage rollup.
   Return ONLY credits — USD stays internal, never serialized.

7) allowance(balance_credits) -> dict mapping friendly service descriptions to how many the balance
   buys, using the SAME per-ratio sums as quote_credits (no independent rounding path):
     {"upscale_images": balance // ratio_credits(upscale, "1:1"),
      "videos_8s": balance // ratio_credits(image_to_video, "16:9", duration_seconds=8),
      "media_kits": balance // quote_credits(media_kit, ratios=all 3, duration_seconds=5).total_credits}.

Unit-test the math: (a) a media_kit quote at defaults yields the expected integer credits;
(b) **quote_credits(media_kit).total_credits == sum(ratio_credits(media_kit, r) for r in the 3
ratios)** — this reconciliation assertion is mandatory; (c) no USD value appears in any returned dict.
```

## Verify
`pytest tests/test_pricing.py` passes — including the assertion that `total_credits` equals the sum of `ratio_credits` over the requested ratios (so refunds always reconcile); printing a `quote_credits("media_kit", ...)` result shows **only** credits and a per-ratio breakdown — **no USD keys anywhere**.

# 08 — Quotation / Pricing Engine (credits only — NO balance check)

> **Changed for the Wix model.** Balance lives in Wix CMS, so our quotation no longer checks
> affordability. It is a **pure pricing service**: given a service + params, return credits +
> breakdown. Wix compares that to the member's CMS balance and decides.

## Pure pricing flow

```
 POST /v1/quotation {service, params, member_id}
        │  pricing.quote_credits(service, params)   (from 03; cost×3.2÷peg, USD hidden)
        ▼
   { total_credits, breakdown[ {stage, quantity, credits} ] }   ← credits only, no USD, no balance

 POST /v1/pricing/allowance {balance}
        │  pricing.allowance(balance)
        ▼
   { allowance: { upscale_images, videos_8s, media_kits } }     ← Wix passes the CMS balance in
```

## Per-ratio cost map (drives proportional refunds in the worker)

```
 media_kit credits = Σ over ratios of (upscale + outpaint? + i2v)
 ratio_credits(ratio) is exposed so the worker can refund exactly the failed ratios.
```

## Prompt

```
app/wallet/quotation.py — QuotationEngine (pure pricing; no repo/balance):
- estimate(service, params) -> {service, total_credits, breakdown}. Uses pricing.quote_credits
  (whose total is Σ per-ratio canonical units — see prompt 03). Validate params per service
  (image_to_video & media_kit require room_name; reject unknown ratios). NO balance/affordability logic.
- allowance(balance:int) -> {allowance: {...}} via pricing.allowance.
- ratio_credits(service, ratio, params) -> int : MUST delegate to pricing.ratio_credits (prompt 03)
  — do NOT re-implement the rounding here. It is the single canonical per-ratio unit the worker
  refunds. Re-export it so the worker imports one definition only.
Wrap in obs @span("quotation.*").
Unit test (mandatory reconciliation): for media_kit AND image_to_video with the 3 ratios,
  estimate(...).total_credits == Σ ratio_credits(service, r, params) over the requested ratios
  (exact equality — this is what guarantees refunds never over/under-pay). allowance(0) yields
  zeros; no USD anywhere.
```

## Verify
`tests/test_quotation_engine.py` passes; `estimate` returns credits+breakdown with no balance/USD fields; `ratio_credits` is the SAME function used in pricing (prompt 03) and, summed over ratios, equals the media-kit total **exactly**.

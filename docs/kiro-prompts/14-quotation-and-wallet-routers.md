# 14 — Quotation & Pricing Routers (wallet endpoints removed)

> **Changed for the Wix model.** The wallet (balance, top-up) is **owned by Wix CMS** — those
> endpoints do **not** exist on our API. We expose only **pricing**: a quotation and an allowance
> calculator that Wix calls so pricing logic stays in one place.

## Endpoint map

```
 POST /v1/quotation          {service, params, member_id} → {total_credits, breakdown}   (Auth)
 POST /v1/pricing/allowance  {balance, member_id}         → {allowance{...}}             (Auth)
 GET  /v1/metrics-lite       queue depth / active jobs / fal sem / refund failures        (Auth)

 (REMOVED: GET /v1/wallet, POST /v1/wallet/top-up — Wix owns balance & Stripe-only grants)
```

## Where pricing authority lives

```
 Wix .web.js (getQuote / getWallet)
        │ calls
        ▼
 FastAPI /v1/quotation + /v1/pricing/allowance   ← single source of pricing truth (prompt 03)
        │ returns credits only (USD never leaves the server)
        ▼
 Wix compares to CMS balance & decides affordability
```

## Prompt

```
app/routers/quotation.py:
- POST /v1/quotation (QuotationRequest, Auth) -> QuotationResponse-without-balance:
  {service, total_credits, breakdown}. Calls QuotationEngine.estimate. No hold, no balance.
- POST /v1/pricing/allowance (Auth, body {balance:int}) -> {allowance: {...}} via
  QuotationEngine.allowance.

Do NOT implement /v1/wallet or /v1/wallet/top-up — balance + grants are Wix CMS + Stripe only.

app/routers/metrics.py:
- GET /v1/metrics-lite (Auth): queue depth, active jobs, fal semaphore in-use, and a counter of
  failed Wix refund callbacks (so unbilled refunds are visible).

Tag routes "quotation" / "pricing" / "metrics". Wrap handlers in obs @span. All responses
credits-only (no USD). Embed the pricing-authority ASCII as a comment atop quotation.py.
```

## Verify
`POST /v1/quotation` returns credits + breakdown (no balance/USD); `POST /v1/pricing/allowance` with a balance returns the friendly counts; `/v1/wallet*` routes do not exist (404).

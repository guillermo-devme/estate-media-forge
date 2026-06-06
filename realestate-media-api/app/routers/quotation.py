"""Quotation & pricing routers (credits only — Wix owns the wallet).

Where pricing authority lives

Wix .web.js (getQuote / getWallet)
       | calls
       v
FastAPI /v1/quotation + /v1/pricing/allowance   <- single source of pricing truth (prompt 03)
       | returns credits only (USD never leaves the server)
       v
Wix compares to CMS balance & decides affordability

NOTE: /v1/wallet and /v1/wallet/top-up are intentionally NOT implemented —
balance + grants live in Wix CMS (Stripe-only).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import Auth
from app.obs.spans import span_ctx
from app.schemas.requests import AllowanceRequest, QuotationRequest
from app.schemas.responses import AllowanceResponse, QuotationResponse
from app.wallet.quotation import QuotationEngine

router = APIRouter(prefix="/v1")

_engine = QuotationEngine()


@router.post(
    "/quotation",
    response_model=QuotationResponse,
    tags=["quotation"],
    summary="Quote a service in credits",
    description="""Pure pricing: returns `total_credits` + per-stage breakdown. No balance check, no USD.

**Purpose:** Wix calls this *before* decrementing the member's wallet so it knows how many credits
to hold. The pricing math (provider cost × earnings ratio ÷ credit peg) lives only here — Wix
never computes it independently.

**Use case — pre-flight quote on the Generator page:**

1. Member selects a room photo and picks "Media Kit".
2. Frontend calls `getQuote('media_kit', { image_url, room_name })` (Velo web method).
3. Velo calls this endpoint → receives `total_credits` + breakdown.
4. Velo compares `total_credits` to the CMS balance → shows "This costs X credits" or "You need Y more".
5. If sufficient, the "Generate" button is enabled.

```
 Frontend           Velo .web.js            FastAPI /v1/quotation
 ────────           ────────────            ─────────────────────
 getQuote() ──────▶ auth + role check
                    POST /v1/quotation ───▶ pricing.quote_credits(service, params)
                    ◀──── {total_credits, breakdown} ◀─── ceil per ratio, USD hidden
                    CMS balance ≥ credits?
 ◀── {credits, sufficient, short_by}
```

No side effects. Call as many times as needed (idempotent, stateless).
""",
)
async def quote(req: QuotationRequest, auth: Auth) -> QuotationResponse:
    """Price a service in credits (with per-stage breakdown). No balance/USD."""
    if req.member_id != auth.member_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    async with span_ctx("quotation.quote"):
        params = req.model_dump(mode="json")
        try:
            result = await _engine.estimate(req.service, params)
        except ValueError as exc:
            # Bad params (missing room_name / unknown ratio) — safe message, no USD.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return QuotationResponse.model_validate(result)


@router.post(
    "/pricing/allowance",
    response_model=AllowanceResponse,
    tags=["pricing"],
    summary="Allowance for a balance",
    description="""Given a Wix-provided credit balance, returns how many of each service it buys.

**Purpose:** Powers the "Your credits ≈ 500 upscales, or 5 videos, or 2 media kits" display on the
member dashboard. Pricing is computed by the same `ratio_credits` function used for quoting and
refunding, so the numbers always agree.

**Use case — wallet display:**

1. Member opens their dashboard.
2. Velo calls `getWallet()` → reads CMS balance, then calls this endpoint with that balance.
3. FastAPI returns friendly counts: `{ upscale_images, videos_8s, media_kits }`.
4. Frontend renders "Your X credits ≈ ...".

```
 Frontend           Velo .web.js                 FastAPI /v1/pricing/allowance
 ────────           ────────────                 ────────────────────────────
 getWallet() ─────▶ CMS balance read
                    POST /v1/pricing/allowance ─▶ pricing.allowance(balance)
                    ◀──── { allowance: {upscale_images, videos_8s, media_kits} }
 ◀── "Your 10000 credits ≈ 500 upscales, 5 videos, 2 media kits"
```

Stateless, no side effects. The allowance uses the same per-ratio pricing that quotes and refunds
use — so the member never sees contradictory numbers.
""",
)
async def allowance(req: AllowanceRequest, auth: Auth) -> AllowanceResponse:
    """How many of each service a Wix-provided credit balance buys."""
    if req.member_id != auth.member_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    async with span_ctx("quotation.allowance"):
        result = await _engine.allowance(req.balance)
    return AllowanceResponse.model_validate(result)

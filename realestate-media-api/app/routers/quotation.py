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
    description="Pure pricing: returns total_credits + per-stage breakdown. No balance, no USD.",
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
    description="Given a Wix-provided credit balance, returns how many of each service it buys.",
)
async def allowance(req: AllowanceRequest, auth: Auth) -> AllowanceResponse:
    """How many of each service a Wix-provided credit balance buys."""
    if req.member_id != auth.member_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    async with span_ctx("quotation.allowance"):
        result = await _engine.allowance(req.balance)
    return AllowanceResponse.model_validate(result)

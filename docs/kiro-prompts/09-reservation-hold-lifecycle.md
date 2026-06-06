# 09 — (Superseded — holds moved to Wix)

> Under the Wix integration, the **hold = a Wix-side atomic decrement** before submit (see
> `../wix-integration/velo/backend/lib/wallet.js`, `spend()`), and **refunds** come back to our
> worker → Wix `post_falRefund` http-function. There is **no TTL-hold lifecycle inside FastAPI**.

What replaces this prompt:

```
 reserve  → Wix wallet.spend(member, credits, clientRef)   (per-member unique-_id lock)
 settle   → success: nothing to do (already decremented)
            partial/failure: FastAPI worker → POST WIX_REFUND_URL (HMAC) → wallet.refund(...)
 idempotency → spend_{clientRef} / refund_{jobId} rows in Wix TokenTransactions
```

➡️ The FastAPI worker's refund-callback contract is specified in `12-job-store-and-worker.md`.
No FastAPI code is generated from this prompt.

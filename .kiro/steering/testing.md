---
inclusion: fileMatch
fileMatchPattern: "**/*.py"
---

<!-- Loads alongside python-fastapi.md whenever Python is in context (where the testing rigor lives:
     pricing math, HMAC, ledger reconciliation). Velo-side test expectations live in velo-wix.md and
     wix-integration/SETUP.md. Pull in with #testing manually if writing tests outside *.py. -->

# Testing Standards

Every feature ships with tests. No "I ran it once" — prove it.

## FastAPI (pytest + pytest-asyncio)
- **Unit-test pure logic** hard: pricing math (cost × 3.2 ÷ peg → credits, USD never leaks),
  `ratio_credits` summing to the media-kit total, HMAC verification (tampered body / replayed
  nonce / skewed timestamp / member mismatch all → 401), usage-ledger reconciliation.
- **Mock externals**: fal (queue submit/poll), Redis, and the Wix refund callback. No live network
  in unit tests. Assert retries skip 4xx and back off on 5xx.
- **Integration**: submit endpoints return `202` fast; `GET /v1/jobs/{id}` enforces member
  ownership (404 on mismatch); worker fan-out runs 3 ratios and fires a **proportional refund** on
  partial failure.
- Cover the unhappy paths: insufficient signature, bad params, fal failure, refund-callback
  failure (must be logged loudly).

## Velo / wix-site
- Keep balance logic in `lib/wallet.js` pure enough to test the lock/grant/spend/refund flows
  (idempotency on tx `_id`, insufficient-credits rejection, stale-lock recovery). Use the
  mock/test harness rather than hitting live CMS where possible.
- Verify role gating: a `member` calling a `pro` service is rejected before any spend.

## Bar to merge
- New/changed code has tests; the suite passes; lint is clean. Don't mark a task complete with
  failing tests or partial implementation. Add a regression test for every bug fixed.
- Aim for meaningful coverage of money/auth/external-I/O paths over raw % targets.

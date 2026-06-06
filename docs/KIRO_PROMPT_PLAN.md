# ⚠️ Superseded

This monolithic plan has been replaced by a per-prompt file set with ASCII diagrams and the new
**quotation + token-wallet** layer.

➡️ Start at **`kiro-prompts/INDEX.md`** (FastAPI side) and **`wix-integration/INDEX.md`** (Wix/Velo
side). Run the prompt files `01` → `17` in order.

```
kiro-prompts/                          ← FastAPI compute service (build with Kiro)
├── INDEX.md                          ← global architecture, decisions, build order
├── 01-scaffold.md
├── 02-config-and-model-registry.md
├── 03-pricing-and-token-economy.md   ← cost × 3.2 ÷ credit peg (credits, USD hidden)
├── 04-schemas-and-enums.md
├── 05-logging-and-spans.md
├── 06-tenant-auth.md                 ← service key + HMAC (Wix→API trust)
├── 07-usage-ledger.md                ← audit ledger only (balance lives in Wix)
│   07-wallet-and-ledger.md           ← (superseded pointer)
├── 08-quotation-engine.md            ← pricing only (no balance check)
├── 09-reservation-hold-lifecycle.md  ← (superseded — holds moved to Wix)
├── 10-fal-client.md
├── 11-langgraph-pipeline.md
├── 12-job-store-and-worker.md        ← proportional refund → Wix on failure
├── 13-core-routers.md                ← trust Wix HMAC; member_id/client_ref/quoted_credits
├── 14-quotation-and-wallet-routers.md← /v1/quotation + /v1/pricing/allowance (no wallet)
├── 15-openapi-docs.md
├── 16-concurrency-and-backpressure.md
└── 17-postman-and-readme.md          ← HMAC-signed Postman flow

wix-integration/                       ← Wix Studio / Velo (paste into Wix editor)
├── INDEX.md                          ← cross-system architecture, security, data model, roles
├── SETUP.md                          ← collections, secrets, roles, Stripe, test plan
└── velo/backend/                     ← ready-to-paste: lib/*.js, *.web.js, http-functions.js
```

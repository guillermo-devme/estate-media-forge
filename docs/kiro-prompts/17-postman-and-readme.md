# 17 — Postman Collection (HMAC-signed) · Run Scripts · README

> **Changed for the Wix model.** Postman now plays the role of the **Wix Velo backend**: it must
> send the **HMAC-signed** headers our API expects (prompt 06). Wallet/top-up endpoints don't exist
> here (Wix owns balance). The full cross-system flow is tested per `../wix-integration/SETUP.md`.

## What Postman simulates

```
 Postman (acts as Wix .web.js)                FASTAPI
   pre-request script computes:
     ts, nonce, sig = HMAC_SHA256(secret, `${ts}.${nonce}.${member_id}.${sha256(body)}`)
   headers: X-Service-Key, X-Member-Id, X-Timestamp, X-Nonce, X-Signature
        │
        ├─ POST /v1/quotation   ──▶ credits + breakdown
        ├─ POST /v1/media-kit    ──▶ 202 job_id     (body has member_id, client_ref, quoted_credits)
        ├─ GET  /v1/jobs/{id}    ──▶ poll status/assets (ownership enforced by member_id)
        └─ GET  /v1/metrics-lite ──▶ queue/active/refund-fail counters
```

## Golden path (FastAPI in isolation)

```
 1 GET  /health                                 200 ok
 2 POST /v1/quotation {service:media_kit}        → credits + breakdown
 3 POST /v1/media-kit  {member_id, client_ref,
     quoted_credits}                             → 202 {{job_id}}
 4 GET  /v1/jobs/{{job_id}}                       poll → completed (3 ratios w/ video_url)
 5 (neg) tamper body byte → 401 (HMAC)           proves signature enforcement
 6 (neg) GET /v1/jobs/{{job_id}} with other member_id → 404 (ownership)
 7 GET  /v1/metrics-lite
 8 (refund) force a ratio failure → worker POSTs the configured WIX_REFUND_URL
     (point it at a local mock/Beeceptor to observe the signed refund call)
```

## Local process topology

```
 ┌─ redis-server ─┐  ┌─ uvicorn app.main:app ─┐  ┌─ arq app.jobs.worker.WorkerSettings ─┐
 │ jobs + queue   │  │ API(8000)+/docs         │  │ pipeline + fal + refund→Wix          │
 └────────────────┘  └─────────────────────────┘  └──────────────────────────────────────┘
        └──────── SQLite usage.db (audit ledger, NOT balance) ────────┘
   balance truth = Wix CMS (separate; tested via ../wix-integration/SETUP.md)
```

## Prompt

```
Create tests/postman/realestate-media-api.postman_collection.json +
realestate-media-api.local.postman_environment.json (base_url http://localhost:8000).
Env vars: base_url, service_key, service_hmac_secret, member_id, other_member_id, client_ref, job_id.

Add a COLLECTION pre-request script (runs before each request) that, using CryptoJS (built into
Postman):
  - sets ts = floor(Date.now()/1000), nonce = uuid, client_ref = uuid (for submits)
  - computes bodyHash = SHA256(requestBodyString) (empty string for GET)
  - sig = HMAC-SHA256(`${ts}.${nonce}.${member_id}.${bodyHash}`, service_hmac_secret)
  - sets headers X-Service-Key, X-Member-Id={{member_id}}, X-Timestamp, X-Nonce, X-Signature
Ensure the body used for hashing exactly matches the sent body (use a pre-serialized variable).

Requests with tests (golden path order above):
1 GET /health
2 POST /v1/quotation {service:"media_kit", image_url, room_name:"Master Bedroom", member_id}
  → save total_credits as {{quoted_credits}}
3 POST /v1/media-kit {image_url, room_name, member_id, client_ref:{{client_ref}},
  quoted_credits:{{quoted_credits}}} → assert 202, save job_id
4 GET /v1/jobs/{{job_id}} → assert status in set; when completed each ratio has video_url
5 NEGATIVE: duplicate request 3 with one body char changed (break signature) → assert 401
6 NEGATIVE: GET /v1/jobs/{{job_id}} signed as {{other_member_id}} → assert 404
7 GET /v1/metrics-lite

README "Run locally": redis-server; terminal A `uvicorn app.main:app --reload`; terminal B
`arq app.jobs.worker.WorkerSettings`; import collection+env; set service_key, service_hmac_secret
(matching .env), member_id, a sample image_url. List required .env: FASTAPI_SERVICE_KEY,
SERVICE_HMAC_SECRET, WIX_REFUND_URL, FAL_KEY, REDIS_URL, LEDGER_DSN, EARNINGS_RATIO, CREDIT_PEG_USD,
LANGSMITH_*. Note that token balances + Stripe + role checks are exercised on the Wix side
(../wix-integration/SETUP.md), not here.
```

## Verify
With the pre-request signing script, requests 1–4 succeed and a media job reaches `completed` with media URLs; request 5 (tampered body) → 401; request 6 (wrong member) → 404; a forced failure fires a signed refund POST to the configured `WIX_REFUND_URL`.

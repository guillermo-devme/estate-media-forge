# Wix Studio (Velo) Integration — Auth, Roles & Token Wallet

Wix Studio is the production front end **and** the trust layer. Members authenticate in Wix; Velo
`.web.js` web methods enforce **role-based access** and own the **token balance** (Wix CMS). Our
FastAPI service is a pure server-to-server compute backend behind it. Stripe is the *only* path
that adds tokens; only the owning member can spend.

---

## Locked decisions (this layer)

| Area | Decision |
|---|---|
| Balance source of truth | **Wix CMS** (`TokenWallets`, keyed by member `_id`). FastAPI never owns balance. |
| Caller | **Only Velo `.web.js`** calls FastAPI (server-to-server). Frontend never calls FastAPI directly. |
| Add tokens | **Stripe webhook → Wix `http-functions.js` only** (idempotent on Stripe event id). |
| Spend tokens | **Only the authenticated owning member**, enforced in `.web.js` via `currentMember`. |
| Hold / reserve | **Wix-side decrement at submit** (per-member mutex lock). Refund on failure. |
| Roles | **Tiered**, enforced in `.web.js`: `member` → upscale; `pro` → +image_to_video +media_kit; `admin` → adjust/observe. |
| Partial failure | **Proportional refund** for failed aspect ratios. |
| Trust to FastAPI | **Static service key + HMAC-signed body** (member_id + timestamp + nonce). Upgrade path: signed JWT. |
| Concurrency note | Wix Data has **no atomic increment/locking** → we use a **unique-`_id` lock document** mutex per member. |

---

## End-to-end sequence (spend path)

```
 Browser (Wix page)        Velo .web.js (backend)          FastAPI service            ARQ worker / fal
 ─────────────────         ──────────────────────          ───────────────            ────────────────
   submitMediaKit(params)
   ───────────────────────▶ currentMember.getMember()  ── auth (Wix)
                            getRoles() → role check     ── 403 if role lacks service
                            getQuote → POST /v1/quotation ─────────▶ pricing only (credits)
                            ◀──────────────── credits, breakdown ───┘
                            balance = CMS.TokenWallets[_id]
                            balance ≥ credits ?  ── no ─▶ throw InsufficientCredits (402-like)
                              │ yes
                            acquireLock(_id)  (unique-_id insert)
                            decrement balance, write spend tx (idempotent _id=spend_{jobId})
                            releaseLock(_id)
                            POST /v1/media-kit  (HMAC: key+member_id+ts+nonce+sig) ─────▶ verify HMAC
                                                                                          record usage
                                                                          ◀── 202 job_id ─┘ enqueue
   ◀──────────── job_id ────┘                                                              │ fan-out 3
                                                                                           │ pipeline
   getJobStatus(jobId)                                                                     ▼
   ───────────────────────▶ verify Jobs[jobId].memberId == currentMember
                            GET /v1/jobs/{jobId} (HMAC) ──────────────▶ status + assets
   ◀──────── status/assets ─┘                                          ◀───────────────────┘
                                                          on PARTIAL/FAIL: worker POSTs
                                                          Wix http-function /_functions/falRefund
                                                          (HMAC) ─▶ refund proportional credits (idempotent)
```

## Submit idempotency & ambiguous-submit reconciliation

The decrement happens Wix-side **before** FastAPI returns a `job_id`, so the `clientRef` (generated
in `media.web.js`) is the idempotency key tying the two sides together:

```
 spend(member, credits, clientRef)          → tx spend_{clientRef}         (idempotent)
 POST /v1/media-kit { client_ref, ... }      → FastAPI SETNX clientref idx → exactly one job
   ├─ 202 job_id            → record Jobs row, clear any PendingSubmits, done
   ├─ 4xx (rejected)        → job NOT created → refund spend_{clientRef}, throw
   └─ timeout / 5xx (AMBIGUOUS) → job MAY exist → retry once (idempotent); if still ambiguous,
                                  write PendingSubmits[clientRef]; DO NOT refund yet
```

A blind refund on timeout while the job actually runs would mint free credits **and** waste fal
cost; a blind retry without idempotency would create a second fal-spending job. FastAPI is made
exactly-once per `(member_id, client_ref)` (see `../kiro-prompts/13`: `create_job_idempotent` +
`GET /v1/jobs/by-client-ref/{clientRef}`), so retries are safe and the ambiguous case is resolved
by `reconcileSubmit` (scheduled sweep + lazy on dashboard load): it queries FastAPI by clientRef and
either records the job or refunds `spend_{clientRef}` on a definitive 404.

## Add-tokens path (Stripe only)

```
 Stripe ──webhook──▶ Wix http-functions.js  post_stripeWebhook
                       │ verify Stripe signature (raw body)
                       │ idempotency: insert TokenTransactions _id = stripe_{event.id}
                       │   ├─ duplicate ─▶ 200 (already granted, no-op)
                       │   └─ new       ─▶ grant: balance += credits (within member lock)
                       ▼
                     200 OK   (FastAPI is never involved in granting)
```

---

## Security / trust model

```
 trust boundaries
 ┌──────────────┐   member auth      ┌─────────────────┐  HMAC + service key  ┌──────────────┐
 │   Browser    │ ─────────────────▶ │  Velo .web.js   │ ───────────────────▶ │   FastAPI    │
 │ (untrusted)  │  Wix session/SSO   │  (TRUSTED authz)│  egress-allowlisted   │  (compute)   │
 └──────────────┘                    └─────────────────┘                      └──────────────┘
        │                                    │                                        │
        │ cannot call FastAPI directly       │ owns balance + role checks             │ trusts member_id
        │ cannot write CMS directly          │ mints HMAC per request                 │ ONLY from verified HMAC
        ▼                                    ▼                                        ▼
   CMS collections are Admin-only; all access via elevated web methods.

 HMAC per request (Wix → FastAPI):
   sig = HMAC_SHA256(SERVICE_HMAC_SECRET,
                     `${ts}.${nonce}.${member_id}.${sha256(rawBody)}`)
   headers: X-Service-Key, X-Member-Id, X-Timestamp, X-Nonce, X-Signature
   FastAPI verifies: key match · |now-ts| ≤ 300s · nonce unseen (Redis TTL) ·
                     sig valid · header member_id == body member_id
```

> ⚠️ Residual risk of the static-key choice: the service key + HMAC secret together can mint a
> valid spend for any `member_id`. Keep both in Wix Secrets Manager, lock FastAPI ingress to Wix
> egress IPs, and rotate. Migrating to per-request signed JWTs (member claim) closes this fully.

---

## CMS data model

```
 TokenWallets            (Admin read/write; access via elevated web methods only)
   _id        = member._id          ◀── the Wix member id is the wallet key
   balance    : Number (credits, integer ≥ 0)
   updatedDate: Date

 TokenTransactions       (Admin read/write; append-only audit + idempotency)
   _id        : String              ◀── stripe_{eventId} | spend_{jobId} | refund_{jobId} | adjust_{uuid}
   memberId   : String
   type       : "purchase" | "spend" | "refund" | "adjust"
   credits    : Number (signed: + add, − spend)
   balanceAfter: Number
   ref        : String  (stripe event / jobId)
   source     : "stripe" | "service" | "admin"
   createdDate: Date

 TokenLocks              (mutex; insert to acquire, delete to release)
   _id        = member._id
   createdDate: Date (stale-lock cutoff ~30s)

 Jobs                    (ownership + audit so getJobStatus can verify the caller)
   _id        = jobId (from FastAPI)
   memberId   : String
   service    : String
   quotedCredits: Number
   clientRef  : String              ◀── links the job back to its spend_{clientRef}
   status     : String
   createdDate: Date

 PendingSubmits          (ambiguous-submit parking; reconciled then deleted)
   _id        = clientRef           ◀── matches spend_{clientRef}
   memberId   : String
   service    : String
   quotedCredits: Number
   params     : Object              ◀── enough to resolve via GET /v1/jobs/by-client-ref/{clientRef}
   status     : "pending_reconcile"
   createdDate: Date
```

> Note: `TokenTransactions._id` for a spend is `spend_{clientRef}` (the clientRef IS the spend ref),
> and the worker's proportional refund is `refund_{jobId}`; a reconciliation refund for a submit that
> never landed is `refund_{clientRef}`. All three are distinct, so they never collide.

## Balance algebra (Wix-side)

```
 balance(TokenWallets._id) is the cached truth, mutated only inside the member lock.
 audit invariant:  balance == Σ TokenTransactions.credits  (per memberId)
 available == balance   (no separate hold field; the decrement IS the hold)
```

---

## Tiered role matrix (default — editable in SETUP.md)

```
 role     │ upscale │ image_to_video │ media_kit │ wallet read │ top-up/adjust
 ─────────┼─────────┼────────────────┼───────────┼─────────────┼──────────────
 visitor  │   ✗     │      ✗         │    ✗      │     ✗       │     ✗
 member   │   ✓     │      ✗         │    ✗      │     ✓ (own) │     ✗
 pro      │   ✓     │      ✓         │    ✓      │     ✓ (own) │     ✗
 admin    │   ✓     │      ✓         │    ✓      │     ✓ (all) │     ✓ (adjust only)
 stripe   │  (system, via webhook) ──────────────────────────────▶ purchase grant only
```

Decision tree applied in every spend web method:

```
 logged in?  ── no ─▶ deny (SiteMember required)
   │ yes
 role allows service?  ── no ─▶ 403 forbidden
   │ yes
 balance ≥ quoted credits?  ── no ─▶ insufficient credits
   │ yes
 lock → decrement → spend tx → unlock → call FastAPI
```

---

## File map

```
wix-integration/                     ← design + setup DOCS (this folder)
├── INDEX.md                         ← this file
└── SETUP.md                         ← collections, secrets, roles, wiring, test plan

../wix-site/                         ← the actual Velo PROJECT (paste into Wix)
├── backend/
│   ├── lib/falClient.js             ← HMAC signing + fetch to FastAPI (internal module)
│   ├── lib/wallet.js                ← lock + balance + grant/spend/refund (internal module)
│   ├── lib/roles.js                 ← role→service matrix + assertRole
│   ├── quotation.web.js             ← getQuote (no spend)
│   ├── media.web.js                 ← submit* + getJobStatus
│   ├── wallet.web.js                ← getWallet + adminAdjust
│   └── http-functions.js            ← post_stripeWebhook + post_falRefund
├── pages/Generator.example.js       ← example frontend flow
└── public/{aspectRatios,credits}.js ← shared frontend code
```

Pairs with the FastAPI prompt set in `../kiro-prompts/` (now revised for this trust model).

Sources: [Velo Web Method](https://dev.wix.com/docs/velo/apis/wix-web-module/web-method), [Velo elevate()](https://dev.wix.com/docs/velo/apis/wix-auth/elevate), [Velo identities/roles](https://dev.wix.com/docs/develop-websites/articles/coding-with-velo/authorization/identities), [wix-data update](https://dev.wix.com/docs/velo/apis/wix-data/update), [Velo atomicity discussion](https://community.wix.com/velo/forum/coding-with-velo/atomicity-when-updating-a-field-in-collection)

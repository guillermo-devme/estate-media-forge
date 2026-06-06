# Wix Studio / Velo — Setup Guide

Paste the files from `../wix-site/backend/` into your Wix site's **Backend** section (Velo dev mode
on). `lib/*.js` go under `backend/lib/`; `*.web.js` and `http-functions.js` go directly under
`backend/`. Shared frontend code in `../wix-site/public/` goes under **Public**; page code in
`../wix-site/pages/` goes into the matching page's code panel.

## 1. CMS collections (Content Manager → create collections)

Create four collections. Set **all of them to "Admin" read & write** (no site-member/anyone access)
— every read/write goes through the elevated backend modules.

```
TokenWallets        _id(Text=memberId) · balance(Number) · updatedDate(Date)
TokenTransactions   _id(Text) · memberId(Text) · type(Text) · credits(Number)
                    · balanceAfter(Number) · ref(Text) · source(Text) · reason(Text) · createdDate(Date)
TokenLocks          _id(Text=memberId) · createdDate(Date)
Jobs                _id(Text=jobId) · memberId(Text) · service(Text) · quotedCredits(Number)
                    · clientRef(Text) · status(Text) · createdDate(Date)
PendingSubmits      _id(Text=clientRef) · memberId(Text) · service(Text) · quotedCredits(Number)
                    · params(Object) · status(Text) · createdDate(Date)
```

`TokenTransactions._id` is the idempotency key: `stripe_{eventId}`, `spend_{ref}`,
`refund_{jobId}`, `adjust_{uuid}`. Uniqueness of `_id` is what makes grants/refunds exactly-once.

`PendingSubmits` (five collections total now) holds submits whose FastAPI call returned an
**ambiguous** result (timeout/5xx): the wallet was already decremented but we don't yet know if a
job was created, so we must NOT blindly refund. `reconcileSubmit` (in `media.web.js`) resolves each
one via `GET /v1/jobs/by-client-ref/{clientRef}` — recording the job if it exists, or refunding
`spend_{clientRef}` if FastAPI definitively has no such job (404). Run it from a **scheduled job**
(every few minutes) and opportunistically when a member opens their dashboard. spend (`spend_{clientRef}`)
and refund (`refund_{clientRef}`) are both idempotent, so reconciliation is safe to repeat.

## 2. Member roles (Members area → Roles/Badges)

Create roles named exactly (lowercase match in `lib/roles.js`): `pro`, `admin`.
Everyone logged in is treated as `member` by default. Adjust the matrix in `lib/roles.js`.

```
 member → upscale
 pro    → upscale + image_to_video + media_kit
 admin  → all + adminAdjust
```

## 3. Secrets (Settings → Secrets Manager)

```
FASTAPI_BASE_URL        e.g. http://localhost:8000   (your service base; no trailing slash)
FASTAPI_SERVICE_KEY     shared static service key (also configured in FastAPI)
SERVICE_HMAC_SECRET     shared HMAC secret (also in FastAPI) — signs Wix→API and API→Wix refund
STRIPE_WEBHOOK_SECRET   from Stripe dashboard (whsec_...)
```

> Keep these only in Secrets Manager. Lock FastAPI ingress to Wix egress IPs. Rotate periodically.

## 4. Stripe

When you create the Checkout Session (or PaymentIntent), attach metadata so the webhook knows who
to credit and how much:

```js
metadata: { member_id: "<wix member _id>", credits: "1000" }
```

Point your Stripe webhook at: `https://<your-site>/_functions/stripeWebhook`
Subscribe to `checkout.session.completed` (and/or `payment_intent.succeeded`).

## 5. FastAPI refund callback

Set these in the FastAPI `.env` so the worker can call back on partial/total failure:

```
WIX_REFUND_URL=https://<your-site>/_functions/falRefund
FASTAPI_SERVICE_KEY=<same as Wix>
SERVICE_HMAC_SECRET=<same as Wix>
```

## 6. Frontend usage (Wix page code)

```js
import { getQuote } from 'backend/quotation.web.js';
import { submitMediaKit, getJobStatus } from 'backend/media.web.js';
import { getWallet } from 'backend/wallet.web.js';

// show what their balance buys
const { balance, allowance } = await getWallet();
// → allowance e.g. { upscale_images: 166, videos_8s: 6, media_kits: 7 }

// pre-flight quote
const q = await getQuote('media_kit', { image_url, room_name: 'Master Bedroom' });
if (!q.sufficient) return showTopUp(q.short_by);

// spend + submit (decrement happens server-side, inside the member lock)
const job = await submitMediaKit({ image_url, room_name: 'Master Bedroom' });

// poll
const status = await getJobStatus(job.job_id); // { status, assets: [...] }
```

## 7. Local test plan

```
 1 Stripe test event → /_functions/stripeWebhook (metadata member_id+credits)
     → TokenWallets[member].balance increases; a stripe_{id} tx row appears
 2 Re-send the SAME event → no double credit (idempotent)
 3 getWallet() → balance + allowance counts
 4 getQuote('media_kit',…) → credits + sufficient flag (no decrement yet)
 5 submitMediaKit(…) → balance drops by credits; spend_{clientRef} tx; Jobs row created; job_id returned
 6 getJobStatus(job_id) → polls FastAPI; ownership enforced (other members get 404)
 7 force a ratio failure in FastAPI → worker calls /_functions/falRefund →
     proportional refund_{jobId} tx; balance partially restored
 8 a "member" (non-pro) calling submitMediaKit → 403 from assertRole
 9 idempotency: replay a submit with the SAME clientRef → FastAPI returns the SAME job_id, only
     ONE job + one spend_{clientRef} (no double charge, no duplicate job)
10 ambiguous submit: point FastAPI at a sink that times out AFTER creating the job → a
     PendingSubmits[clientRef] row appears, NO premature refund; running reconcileSubmit then finds
     the job (GET /v1/jobs/by-client-ref) and clears the intent. Force a true non-landing (FastAPI
     never created it) → reconcileSubmit refunds spend_{clientRef}.
```

## Concurrency note (read this)

Wix Data has **no atomic increment and no locking**. `lib/wallet.js` serializes per-member
mutations with a unique-`_id` lock document in `TokenLocks` (a duplicate insert fails atomically —
the one guarantee Wix provides). Cross-member spends touch different rows, so 100 rps across many
members is fine; only repeated concurrent spends by the *same* member contend, and they serialize
through the lock. The transactions ledger lets you audit/rebuild any balance.

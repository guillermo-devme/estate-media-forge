# Real-Estate Media-Kit API — Kiro Prompt Plan (Index)

Async, low-latency API that turns a property photo into a 3-aspect-ratio media kit
(upscale → expand/outpaint → cinematic image-to-video) via **fal.ai**, orchestrated by
**LangGraph**, fronted by **Wix Studio (Velo)** which owns member auth, roles, and the token
balance, with full token/cost/timing observability.

> **Trust model:** Wix Studio (Velo) is the front end + auth/RBAC + balance-of-record layer. The
> token wallet lives in **Wix CMS** (Stripe-only top-ups, member-only spend). This FastAPI service
> is a server-to-server compute backend behind Wix — see **`../wix-integration/INDEX.md`** for the
> Velo code and the full cross-system flow. The prompts below build the FastAPI side.

Paste the prompt files into Kiro **in numeric order**. Each file opens with ASCII diagrams so the
data flow / state machine for that layer is unambiguous, then a single copy-paste prompt block,
then a **Verify** step. When `17-postman-and-readme.md` is done, the whole thing runs locally and
is testable in Postman at `http://localhost:8000`. **No deployment infra is specified.**

---

## Locked Decisions

| Area | Decision |
|---|---|
| Language / framework | Python 3.11+, FastAPI, **Pydantic v2** (replaces zod) |
| Async queue | **ARQ + Redis** — API returns `202` instantly |
| Result delivery | **Polling** — Wix calls `GET /v1/jobs/{job_id}` |
| Caller / auth | **Only Wix Velo backend** calls us; **static service key + HMAC-signed body** (member_id + ts + nonce). No per-end-user keys. |
| AI provider | **fal.ai** (config-swappable model registry) |
| Default models | Upscale = **Clarity Upscaler**, Expand = **FLUX 2 Pro Outpaint**, I→V = **Seedance 2** |
| Media kit | Auto **1:1 / 9:16 / 16:9**; one request → **3 fan-out sub-jobs**; outputs to local `/media` |
| Orchestration | **LangGraph `StateGraph`**; fal calls wrapped as LangChain tools |
| Observability | GCloud-compatible **JSON logs** + nested **span/timer** + **LangSmith** token/cost |
| API docs | Built-in **Swagger `/docs` + ReDoc `/redoc`** |
| **Token model** | **Abstract credits — USD hidden.** Internal: `cost × 3.2 ÷ peg → credits`. Pricing math lives in FastAPI; users only ever see credits. |
| **Earnings ratio** | **3.2x** default, configurable |
| **Balance authority** | **Wix CMS** (`TokenWallets` by member `_id`). FastAPI keeps an **append-only usage/audit ledger only** (SQLite, pluggable). |
| **Add / spend / hold** | Add = **Stripe webhook → Wix only**. Spend/hold = **Wix-side atomic decrement** at submit. Failure = **worker → Wix refund callback** (proportional per failed ratio). |
| Concurrency target | Absorb **~100 req/s**; bounded fal concurrency + queue backpressure |
| Deployment | **Out of scope** — no Docker/cloud/k8s unless asked later |

---

## Global Architecture (Wix-fronted)

```
 Browser (Wix)        Wix Velo .web.js (auth+roles+balance)        FASTAPI (compute)        worker/fal
 ───────────          ─────────────────────────────────────        ─────────────────        ──────────
  getQuote ─────────▶ member auth · role check
                      POST /v1/quotation (HMAC) ──────────────────▶ pricing only ─▶ credits
                      ◀──────────────────────────── credits ───────┘
                      CMS balance ≥ credits? (Wix decides)
  submitMediaKit ───▶ lock · decrement CMS (the "hold") · spend tx
                      POST /v1/media-kit (HMAC, member_id,          verify HMAC · usage event
                      client_ref, quoted_credits) ────────────────▶ create job ─▶ ARQ enqueue
  ◀──── job_id ───────◀──────────────────────────── 202 job_id ────┘                  │ fan-out 3
                                                                                       │ pipeline
  getJobStatus ─────▶ verify ownership                                                 ▼
                      GET /v1/jobs/{id} (HMAC) ───────────────────▶ status + assets
  ◀── status/assets ──◀─────────────────────────────────────────── ◀─── /media/* static
                                                       on PARTIAL/FAIL: worker ─▶
                      Wix /_functions/falRefund ◀───── HMAC {member_id,job_id,refund_credits}
                      refund proportional (idempotent)

  Stripe ──webhook──▶ Wix /_functions/stripeWebhook ─▶ grant credits to CMS (ONLY add-path)
```

---

## Spend lifecycle (where each step lives)

```
 QUOTE     FastAPI /v1/quotation        pure pricing (credits, USD hidden)
 HOLD      Wix wallet.spend()           atomic decrement via unique-_id member lock
 EXECUTE   FastAPI + ARQ + fal          fan-out 3 ratios, LangGraph pipeline
 SETTLE    success → nothing (already debited)
           partial → worker refunds Σ(failed-ratio credits) → Wix /_functions/falRefund
           failure → worker refunds full quoted_credits → Wix /_functions/falRefund
 AUDIT     FastAPI usage ledger (events)  ⇄ reconciles to  Wix TokenTransactions (balance truth)
```

---

## Build Order (one prompt per file)

```
 01 ─ scaffold ──────────────┐
 02 ─ config + model registry │ foundations
 03 ─ pricing & token economy │  (cost table, 3.2x, credit peg)
 04 ─ schemas + enums ────────┘
 05 ─ logging + spans
 06 ─ service auth (HMAC) + member identity        [revised for Wix]
 07 ─ usage / audit ledger (no balance authority)  [revised → 07-usage-ledger.md]
 08 ─ quotation / pricing engine (no balance check)[revised]
 09 ─ (superseded — holds moved to Wix)
 10 ─ fal.ai async client
 11 ─ LangGraph pipeline
 12 ─ job store + ARQ worker (proportional refund → Wix)  [revised]
 13 ─ FastAPI app + core routers (trust Wix HMAC)         [revised]
 14 ─ quotation + pricing routers (wallet endpoints removed) [revised]
 15 ─ OpenAPI / Swagger / ReDoc polish
 16 ─ concurrency + backpressure
 17 ─ Postman (HMAC-signed) + run scripts + README        [revised]
```

Dependency graph (what must exist before a prompt):

```
 01
 ├─▶ 02 ─▶ 03 ──────────────┐
 ├─▶ 04 (uses 02,03 enums)   │
 ├─▶ 05                      │
 └─▶ 06 (HMAC service auth)  │
        03 ─▶ 08 (pricing)   │     07 (usage ledger) ─┐
        02 ─▶ 10 ─▶ 11        │                        │
        08,11,07 ─▶ 12 (worker+refund→Wix) ◀──────────┘
        04,05,06,12 ─▶ 13 ─▶ 14
        13,14 ─▶ 15 ─▶ 16 ─▶ 17
   (09 produces no code — holds live in ../wix-integration)
```

> The original monolithic `KIRO_PROMPT_PLAN.md` is **superseded** by this folder. The Wix/Velo
> side (auth, roles, wallet, Stripe, refund callback) lives in **`../wix-integration/`**.

---

## Durability & deployment scope (read before calling it "done")

Deployment is **deliberately out of scope** for prompts 01–17 — but be explicit about what that
means so "the Postman golden path passes" is not mistaken for "production-ready". As specified, the
system is a **local, single-host demo**; the following must be added before it can serve a live Wix
site, and Kiro should NOT silently assume them away:

| Concern | As built (local) | What real use needs |
|---|---|---|
| Reachability | `PUBLIC_BASE_URL` / `FASTAPI_BASE_URL` = `http://localhost:8000` | An HTTPS host Wix egress can reach, **ingress locked to Wix egress IPs** (the static-key+HMAC threat model in `../wix-integration/INDEX.md` depends on this) |
| Job state + queue | Redis, **job records TTL 24h**, no persistence configured | Redis **persistence (AOF/RDB)** + restart policy — otherwise a Redis restart loses in-flight jobs AND the ARQ queue, stranding already-charged work |
| Generated media | local disk `MEDIA_DIR`, served via StaticFiles, never cleaned | durable object storage (e.g. signed URLs) + a retention/cleanup policy; local disk does not survive redeploys and grows unbounded |
| Usage ledger | SQLite (`LEDGER_DSN`) | the pluggable DSN is already there — point it at Postgres + backups for multi-host/observability |
| Crash between charge & job | covered: Wix `PendingSubmits` reconciliation (P4) | keep the scheduled `reconcileSubmit` sweep running so stranded charges self-heal |

`12-job-store-and-worker.md` and `16-concurrency-and-backpressure.md` carry the specifics. The
deliverable for 01–17 is "runs locally and passes the signed Postman flow"; deploying it is a
separate, later decision. State this boundary in the README rather than implying full production
readiness.

Sources: [fal.ai](https://fal.ai/), [Clarity Upscaler](https://fal.ai/models/fal-ai/clarity-upscaler/api), [FLUX 2 Pro Outpaint](https://fal.ai/models/fal-ai/flux-2-pro/outpaint/api), [Seedance 2 image-to-video](https://fal.ai/models/bytedance/seedance-2.0/image-to-video/api)

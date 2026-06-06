# realestate-media-api

Async compute backend that turns a property photo into a 3-aspect-ratio media kit
(1:1, 9:16, 16:9) via **upscale → expand/outpaint → cinematic image-to-video**, powered by
**fal.ai** and orchestrated with **LangGraph**.

This service is a **server-to-server compute backend** fronted by a Wix Studio (Velo) site.
Wix owns member auth, roles, and the **token balance of record** (Wix CMS). This service owns
**no money/balance** — it keeps an append-only usage/audit ledger only. See
`../docs/wix-integration/INDEX.md` for the cross-system flow.

## Run locally

```bash
# 1. Create and activate a virtualenv
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install (editable) with dev tools
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env   # then fill in values

# 4. Boot the API
uvicorn app.main:app --reload
```

Open http://localhost:8000 — interactive docs land at `/docs` (Swagger) and `/redoc`.

## Running the worker

The API only validates, records usage, and enqueues — all heavy work (fal calls) runs in the ARQ
worker. Run it alongside the API (needs Redis):

```bash
arq app.jobs.worker.WorkerSettings
```

## Local process topology

```
 ┌─ redis-server ─┐  ┌─ uvicorn app.main:app ─┐  ┌─ arq app.jobs.worker.WorkerSettings ─┐
 │ jobs + queue   │  │ API(8000) + /docs       │  │ pipeline + fal + refund → Wix         │
 └────────────────┘  └─────────────────────────┘  └───────────────────────────────────────┘
        └──────── SQLite usage.db (audit ledger, NOT balance) ────────┘
   balance truth = Wix CMS (separate; tested via ../docs/wix-integration/SETUP.md)
```

## Required `.env`

```
FASTAPI_SERVICE_KEY     shared static key (Wix → API)
SERVICE_HMAC_SECRET     shared HMAC secret (both directions)
WIX_REFUND_URL          Wix /_functions/falRefund (worker refund callback)
FAL_KEY                 fal.ai API key
REDIS_URL               redis://localhost:6379
LEDGER_DSN              sqlite+aiosqlite:///./usage.db
EARNINGS_RATIO          3.2
CREDIT_PEG_USD          0.01
LANGSMITH_API_KEY / LANGSMITH_PROJECT / LANGCHAIN_TRACING_V2   (optional tracing)
```

> Token **balances**, **Stripe** top-ups, and **role checks** are exercised on the **Wix** side
> (`../docs/wix-integration/SETUP.md`), not here. This service owns no balance.

## Test with Postman (acts as the Wix Velo backend)

A signed collection lives in `tests/postman/`:

1. Start `redis-server`.
2. Terminal A: `uvicorn app.main:app --reload`
3. Terminal B: `arq app.jobs.worker.WorkerSettings`
4. Import `tests/postman/realestate-media-api.postman_collection.json` and
   `realestate-media-api.local.postman_environment.json`.
5. In the environment set `service_key` + `service_hmac_secret` (matching your `.env`), `member_id`,
   and a sample `image_url`.
6. Run the collection in order. A **collection pre-request script** signs every request with the
   HMAC headers (`X-Service-Key`, `X-Member-Id`, `X-Timestamp`, `X-Nonce`, `X-Signature`), so you
   never sign by hand.

Golden path: `GET /health` → `POST /v1/quotation` (saves `quoted_credits`) → `POST /v1/media-kit`
(202, saves `job_id`) → poll `GET /v1/jobs/{job_id}` to `completed`. Negatives: a tampered
signature → 401; polling another member's job → 404. To observe the signed refund callback, point
`WIX_REFUND_URL` at a local mock (e.g. Beeceptor) and force a ratio failure.

> GET requests carry a minimal `{"member_id": "..."}` body so the signed hash matches the server
> (which hashes the canonical member body for empty GETs).

## Concurrency & backpressure (tuning knobs)

Designed to absorb bursts (~100 req/s) where the heavy work is external. Load is shed/queued at
three points, tuned via `.env`:

| Knob | Default | What it controls |
|---|---|---|
| `MAX_QUEUE_DEPTH` | `500` | If the ARQ queue is at/over this depth, submits return **429 + `Retry-After`** so Wix backs off (no fal work is started). |
| worker `max_jobs` | `20` | Jobs a single worker pulls concurrently (in `app/jobs/worker.py`). |
| `MAX_FAL_CONCURRENCY` | `8` | Hard cap on **real** concurrent fal calls via a shared semaphore — the true throttle on external load. |

The request path does only cheap work: verify HMAC → validate → usage write → Redis write →
enqueue → `202`. No fal calls, no balance logic, no blocking I/O. One shared `httpx.AsyncClient`,
one Redis pool, and one ledger engine are reused process-wide (no per-request client creation).
`GET /v1/metrics-lite` exposes queue depth, active jobs, fal semaphore in-use, and the
failed-Wix-refund counter.

## Durability & deployment boundary (read before calling it "done")

Prompts 01–17 deliver a **local, single-host demo** that passes the signed Postman flow. It is
**not** production-ready as-is. Before serving a live Wix site, you must add (none are assumed here):

- **Redis persistence (AOF/RDB).** Job state *and* the ARQ queue both live in Redis. Without
  persistence, a Redis restart drops in-flight jobs that were **already charged Wix-side**, stranding
  paid work. (Reconciliation via `GET /v1/jobs/by-client-ref/{client_ref}` + the Wix
  `PendingSubmits` sweep mitigates, but persistence is the real fix.)
- **Durable media storage.** `MEDIA_DIR` is local disk served via StaticFiles — dev-only. It does
  not survive redeploys and grows unbounded. Use object storage (e.g. signed URLs) + a
  retention/cleanup policy.
- **Postgres ledger.** Point `LEDGER_DSN` at Postgres + backups for multi-host/observability
  (the DSN is already pluggable).
- **Ingress lockdown.** Lock FastAPI ingress to the Wix egress IP range — the static-key + HMAC
  threat model assumes only Wix can reach us. Rotate the service key + HMAC secret periodically.

See `../docs/kiro-prompts/INDEX.md` → "Durability & deployment scope" for the full checklist.

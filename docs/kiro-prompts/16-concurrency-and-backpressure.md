# 16 — Concurrency, Backpressure & Resource Safety (~100 req/s)

## Where load is absorbed

```
 100 req/s inbound
      │  cheap path: validate + hold check + Redis write + enqueue  (no fal here)
      ▼
 ┌───────────────┐  excess waits here (durable buffer)
 │ ARQ queue      │ ── depth > MAX_QUEUE_DEPTH ─▶ API returns 429 + Retry-After
 │ (Redis)        │
 └──────┬────────┘
        ▼  workers pull (max_jobs=20 each)
 ┌───────────────┐
 │ fal Semaphore  │ ── caps REAL concurrency to fal (MAX_FAL_CONCURRENCY)
 │ (bounded)      │
 └──────┬────────┘
        ▼
   fal.ai queue API
```

## Backpressure decision tree

```
 incoming POST
   ├─ queue_depth ≥ MAX_QUEUE_DEPTH ─▶ 429 {Retry-After}
   └─ else ─▶ enqueue ─▶ 202
 worker pulling
   ├─ fal semaphore full ─▶ awaits (natural throttle, no drop)
   └─ slot free ─▶ run pipeline node
```

## Prompt

```
Harden for ~100 req/s where heavy work is external:
- Confirm POST endpoints do only: verify HMAC (06) + validate + usage write + Redis write +
  enqueue + 202. No fal / no balance / no blocking I/O in the request path.
- Central bounded fal concurrency via the semaphore in fal_client (MAX_FAL_CONCURRENCY).
- ARQ worker: max_jobs (20), job_timeout, keep_result, health_check.
- Inbound backpressure: before enqueue, check Redis queue depth; if > MAX_QUEUE_DEPTH return a
  structured 429 with Retry-After so the Wix backend backs off.
- Single shared httpx.AsyncClient + single Redis pool + single ledger engine (no per-request
  client creation).
- /v1/metrics-lite already lives in prompt 14 (queue depth, active jobs, fal semaphore in-use,
  failed Wix refund callbacks). Wire its counters here.
- Document tuning knobs (MAX_FAL_CONCURRENCY, worker max_jobs, MAX_QUEUE_DEPTH) in the README.
  Embed the load-absorption ASCII as a comment near the backpressure guard.
- DURABILITY (document in README, do not silently assume): because job state + the queue are both in
  Redis, note that production needs Redis persistence (AOF/RDB) so a restart doesn't drop already-
  charged in-flight jobs, durable object storage for MEDIA_DIR outputs (local disk is dev-only and
  grows unbounded — add a retention/cleanup policy), and FastAPI ingress locked to Wix egress IPs.
  Cross-link ../kiro-prompts/INDEX.md "Durability & deployment scope". Scope of 01–17 stays local.
```

## Verify
A script firing 100 quick POSTs returns all 202 in well under a second; jobs drain without error; exceeding `MAX_QUEUE_DEPTH` yields 429 + `Retry-After`; `/v1/metrics-lite` shows bounded fal concurrency and falling queue depth. The README documents the durability/deploy boundary (Redis persistence, media storage, ingress lockdown) rather than implying production readiness.

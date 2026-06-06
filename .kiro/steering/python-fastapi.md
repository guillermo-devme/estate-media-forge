---
inclusion: fileMatch
fileMatchPattern: "**/*.py"
---

# Python / FastAPI Conventions

- **Async all the way**: `async def` endpoints and I/O; never block the event loop (no sync
  `requests`, no blocking sleeps). One shared `httpx.AsyncClient`, one Redis pool, one ledger engine.
- **Pydantic v2** models for every request/response; use `Field(...)` descriptions + `json_schema_extra`
  examples so the OpenAPI docs are rich. No `dict[str, Any]` at API boundaries.
- **Type hints everywhere**; prefer `Annotated` dependencies. Run **ruff** (lint + format) clean.
- **Money math uses `Decimal`**, then converts to integer credits with `math.ceil`. USD never
  appears in any response model or log.
- **Errors**: raise `HTTPException` with correct status (401 auth, 404 ownership, 429 backpressure,
  502/504 upstream). A global handler returns structured JSON; never leak stack traces.
- **Observability**: wrap external calls and pipeline nodes in the `@span` decorator; log structured
  JSON with `job_id`/`member_id`/`span`/`elapsed_ms`. No secrets, tokens, or raw PII in logs.
- **External calls** (fal, Wix refund): bounded by the global semaphore, with timeouts and tenacity
  retries on transient errors only (never retry 4xx). Make side-effects idempotent.
- **The request path never calls fal and never computes balance** — validate, record usage,
  enqueue, return `202`.
- Keep routers thin; put logic in `pipeline/`, `wallet/`, `providers/`. Write a test alongside.

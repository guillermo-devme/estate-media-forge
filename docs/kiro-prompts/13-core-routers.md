# 13 — FastAPI App + Core Routers (trust Wix HMAC · no local balance)

> **Changed for the Wix model.** Wix already authenticated the member, checked the role, and
> decremented credits. Our submit endpoints verify the HMAC (prompt 06), trust `member_id`, record
> usage, and enqueue. **No balance check, no 402 here** — affordability is Wix's job. We still get
> `quoted_credits` + `client_ref` so the worker can refund proportionally on failure.

## Submit flow (fast path — no fal, no balance logic in request thread)

```
 POST /v1/media-kit | /v1/upscale | /v1/image-to-video    (Auth = verify_service_request)
        │ body: { ...params, member_id, client_ref, quoted_credits }
        ▼
 validate schema · usage.record_event(submitted, member_id, quoted_credits, client_ref)
        ▼
 create_job(member_id, service, request, client_ref, quoted_credits, status=queued)
 enqueue on ARQ
        ▼
 202 JobAccepted { job_id, status:queued, poll_url, quoted_credits }
```

## Ownership on read

```
 GET /v1/jobs/{job_id}  (Auth)
   job.member_id == auth.member_id ?  no ─▶ 404 (no enumeration)  yes ─▶ JobStatusResponse
```

## Prompt

```
app/main.py create_app(): configure_logging; mount StaticFiles at "/media"; create ARQ redis pool,
usage ledger engine, and the WixRefundClient on startup / close on shutdown; include routers; set
title/description/version + docs metadata.

Routers (all under /v1; protected by Auth = verify_service_request, except health):
- health.py: GET /health -> {status:"ok"} (no auth); GET /v1/ready pings Redis + ledger.
- media_kit.py: POST /v1/media-kit (MediaKitRequest incl. member_id, client_ref, quoted_credits).
  IDEMPOTENCY (required — P4): FIRST call store.get_job_by_client_ref(member_id, client_ref). If a
  job already exists for this (member_id, client_ref), return 202 with that SAME job_id + poll_url
  and DO NOT create or enqueue a second job (do not re-record usage). Otherwise validate, record
  usage(submitted), create_job_idempotent (SETNX on clientref index), enqueue process_media_job,
  return 202 JobAccepted with quoted_credits + poll_url. NO balance check, NO 402.
  Rationale: Wix decrements once per client_ref, then POSTs us; a Wix retry after a network timeout
  re-sends the same client_ref and must map to the same job_id — never a duplicate fal-spending job.
- upscale.py: POST /v1/upscale → same shape, same client_ref idempotency → process_upscale_job → 202.
- video.py: POST /v1/image-to-video → same shape, same client_ref idempotency → process_i2v_job → 202.
- jobs.py: GET /v1/jobs/{job_id} → get_job; enforce job.member_id == auth.member_id (404 on
  mismatch); return JobStatusResponse (status + assets + quoted/refunded credits).
  Also GET /v1/jobs/by-client-ref/{client_ref} (Auth) → resolve via get_job_by_client_ref(
  auth.member_id, client_ref); 404 if none. This is the reconciliation primitive Wix uses after an
  ambiguous timeout to learn whether its earlier submit actually created a job (and thus whether to
  keep the decrement or refund) — see ../wix-integration/INDEX.md "Ambiguous-submit reconciliation".
All POSTs return 202 immediately — NO fal calls in the request path. The nonce check (prompt 06)
still rejects byte-identical replays inside the 600s window; client_ref idempotency is the
complementary guard for legitimate retries that (correctly) carry a fresh ts/nonce but the same
client_ref. Global exception handler → structured JSON errors logged with span context.
response_model + status_code on every endpoint. Embed the submit-flow ASCII as a comment atop media_kit.py.
```

## Verify
A signed `POST /v1/media-kit` returns 202 instantly with `quoted_credits`; an unsigned/tampered request → 401; `GET /v1/jobs/{id}` returns 404 when `member_id` doesn't match the signed caller. **Idempotency:** two signed submits with the SAME `client_ref` (different ts/nonce) return the SAME `job_id` and create only ONE job/enqueue (verify exactly one `job:{id}` and one `process_*` enqueued).

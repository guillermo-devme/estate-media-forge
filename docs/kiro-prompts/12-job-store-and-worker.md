# 12 — Job Store + ARQ Worker (fan-out · proportional refund callback to Wix)

> **Changed for the Wix model.** Tokens were already decremented Wix-side at submit. The worker
> does NOT debit. On **partial/total failure** it computes the credits for the **failed ratios**
> and calls the Wix `post_falRefund` http-function (HMAC-signed) to refund exactly that portion.

## Worker fan-out + settlement

```
 process_media_job(job_id)
   │ load job, status=running, set_job_context(job_id), record usage(submitted)
   ▼
 fan-out (asyncio.gather, bounded by fal semaphore)
   ├─ 1:1   ─▶ pipeline ─▶ save assets ─▶ update_asset ─▶ usage(ratio_succeeded|ratio_failed)
   ├─ 9:16  ─▶ ...
   └─ 16:9  ─▶ ...
   ▼
 status = all ok → completed | some → partial | none → failed
   ▼
 SETTLEMENT (only if member_id + quoted_credits present)
   refund_credits = Σ ratio_credits(failed ratios)        (from quotation.ratio_credits)
   ├─ refund_credits == 0  → nothing to refund
   └─ refund_credits  > 0  → POST WIX_REFUND_URL (HMAC) {member_id, job_id, refund_credits, reason}
                              record usage(refund_requested) ; idempotent (refund_{job_id} in Wix)
```

## Refund decision tree

```
 job outcome?
   ├─ completed (all ratios ok) ─▶ refund 0
   ├─ partial  (k of n failed)  ─▶ refund Σ credits(failed k ratios)
   └─ failed   (all n failed)   ─▶ refund Σ credits(all ratios) == full
```

## Prompt

```
app/jobs/store.py — Redis job records (key job:{job_id}, TTL 24h, JSON): job_id, member_id,
service, status, request, assets[AssetSet per ratio], client_ref, quoted_credits,
refunded_credits, token_usage, error, created_at, updated_at. Methods: create_job, get_job,
update_job, update_asset, set_status. Single shared redis pool.
IDEMPOTENCY INDEX (required for P4 — safe Wix retries): also maintain a key
clientref:{member_id}:{client_ref} -> job_id (same 24h TTL), written atomically when the job is
created. Add get_job_by_client_ref(member_id, client_ref) and a create_job_idempotent(...) that
uses Redis SETNX on that key: if the key already exists, return the existing job_id WITHOUT creating
a second job or enqueuing again. This makes "create job" exactly-once per (member_id, client_ref),
so a Wix submit retry after a network timeout can never spawn a duplicate fal-spending job.

app/jobs/worker.py — ARQ WorkerSettings (redis, functions, max_jobs=20, job_timeout, keep_result,
on_startup/on_shutdown). Inject the compiled graph, UsageRepository, QuotationEngine, and a
WixRefundClient.
- process_media_job(ctx, job_id): status=running; fan out requested ratios via asyncio.gather (real
  concurrency capped by the fal semaphore); update_asset + usage event per ratio. Final status =
  completed/partial/failed.
- SETTLEMENT: compute refund_credits = sum(quotation.ratio_credits(service, r, params) for each
  FAILED ratio), using the SAME canonical ratio_credits the quote was built from (prompt 03/08).
  Because quoted_credits == Σ ratio_credits(all ratios), the failed-ratio sum reconciles exactly.
  GUARD (defense in depth): refund_credits = min(refund_credits, job.quoted_credits) — never refund
  more than was charged; if all ratios failed, refund_credits MUST equal quoted_credits (assert it,
  and on mismatch log loudly + refund the lesser, since over-refund mints free credits). If > 0,
  call WixRefundClient.refund(member_id, job_id, refund_credits, reason); store refunded_credits;
  record usage(refund_requested). Idempotent on job_id (Wix enforces via refund_{job_id}).
- process_upscale_job / process_i2v_job: reuse graph short-circuited; same refund-on-failure logic.
  Single-asset failure refunds the full quoted_credits (which, per the reconciliation rule, equals
  ratio_credits for that one ratio).
- Save fal outputs to MEDIA_DIR/{job_id}/{ratio}/ and rewrite asset URLs to
  {PUBLIC_BASE_URL}/media/{job_id}/{ratio}/{filename}.

app/providers/wix_client.py — WixRefundClient.refund(member_id, job_id, credits, reason): POST
WIX_REFUND_URL with the SAME HMAC scheme used inbound (X-Service-Key, X-Timestamp, X-Nonce,
X-Signature over `{ts}.{nonce}.{member_id}.{sha256(body)}`). Retry transient errors (tenacity);
log via obs @span("wix.refund"). Refund failures must be logged loudly (money owed back to user).

app/jobs/enqueue.py — get_arq_pool() + enqueue helpers.
Embed the refund decision-tree ASCII as a comment near the settlement block.

DURABILITY NOTE (comment it in store.py): job records AND the ARQ queue both live in Redis, so job
state survives only as long as Redis does. For local/dev this is fine; for any real use Redis MUST
run with persistence (AOF/RDB) or a Redis restart loses in-flight jobs that were already charged
Wix-side. The 24h TTL is a dev convenience — generated media + the Jobs ownership row outlive it on
the Wix side. Do not treat Redis as the durable record of truth (the Wix CMS ledger is). See
../kiro-prompts/INDEX.md "Durability & deployment scope".
```

## Verify
A media job with one forced ratio failure ends `partial`, and the worker POSTs a refund to the Wix refund URL for exactly that ratio's credits (verify the Wix `TokenTransactions` gets a `refund_{job_id}` row and balance rises by the per-ratio amount). A fully successful job triggers no refund.

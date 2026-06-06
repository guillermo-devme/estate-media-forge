# 07 — Usage / Audit Ledger (NO balance authority)

> **Changed for the Wix model.** The authoritative token balance now lives in **Wix CMS**. Our
> service no longer owns balances, holds, or `available`. It keeps an **append-only usage ledger**
> for observability, reconciliation, and per-ratio refund accounting only.

## What we record (append-only)

```
 usage_events(
   id PK, member_id, job_id, service, event_type,
   credits_quoted, credits_charged, credits_refunded,
   ratio (nullable), note, created_at )

 event_type ∈ { quoted, submitted, ratio_succeeded, ratio_failed, refund_requested, settled }
```

## Reconciliation view (audit, not authority)

```
 our usage ledger  ──┐
                     ├─▶ compare per member_id/job ─▶ should match Wix TokenTransactions
 Wix TokenTransactions ┘            (spend_{ref}, refund_{jobId})
 mismatch ⇒ alert (a refund/spend dropped somewhere)
```

## Prompt

```
Replace any "balance/hold" notion with an append-only usage ledger (still pluggable repo, default
SQLite via settings.ledger_dsn; Postgres later).

app/wallet/models.py — UsageEvent (fields per the diagram). Enum UsageEventType.
app/wallet/repository.py — async UsageRepository: record_event(...), list_for_job(job_id),
list_for_member(member_id), and a reconcile_summary(job_id) returning quoted vs charged vs
refunded. create_all() bootstrap. NO get_balance / get_available / hold logic — balance is Wix's.
Wrap writes in obs @span("usage.*"). Add a top-of-file comment stating balance authority is Wix CMS
and this ledger is audit-only.
Unit test: recording submitted + 2 ratio_succeeded + 1 ratio_failed + refund_requested produces a
correct reconcile_summary.
```

## Verify
`tests/test_usage_ledger.py` passes; the repo exposes **no** balance/hold methods; a job's events summarize quoted/charged/refunded correctly.

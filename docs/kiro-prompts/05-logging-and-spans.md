# 05 — Structured Logging + Nested Span/Timer

## Nested span trace (how you find bottlenecks)

```
 set_job_context(job_id, ratio)              contextvars span stack
 ┌──────────────────────────────────────────────────────────────────┐
 │ media_kit                              elapsed_ms=8120              │
 │  └─ ratio_9:16                         elapsed_ms=8090              │
 │      ├─ upscale     (fal.clarity)      elapsed_ms=1900   ◀ ok       │
 │      ├─ outpaint    (fal.flux-2)       elapsed_ms=2100   ◀ ok       │
 │      └─ i2v         (fal.seedance-2)   elapsed_ms=4080   ◀ BOTTLENECK│
 └──────────────────────────────────────────────────────────────────┘
   each line = one JSON log row: {severity, job_id, ratio, span, parent_span, depth, elapsed_ms}
```

## Span lifecycle

```
 enter ──▶ log "span.start" ──▶ [run] ──┬─ ok  ──▶ log "span.end"   (+elapsed_ms)
                                        └─ raise▶ log "span.error" (+elapsed_ms) ─▶ re-raise
```

## Prompt

```
app/obs/logging.py — JSON logger compatible with Google Cloud Logging (python-json-logger).
Emit: severity (map INFO/WARNING/ERROR/DEBUG to GCloud severities), message, timestamp (RFC3339),
plus arbitrary extras. Provide get_logger(name) and configure_logging(level) for startup.

app/obs/spans.py — nestable async span timer using contextvars to hold a span stack.
- set_job_context(job_id, ratio=None): binds job_id/ratio into the logging context.
- @span("name") decorator for async functions: logs "span.start" then "span.end" with
  elapsed_ms (time.perf_counter); on exception logs "span.error" + elapsed_ms and re-raises.
- span_ctx("name"): async context manager for inline blocks.
Each emitted record must include: job_id, ratio, span (dotted path e.g.
"media_kit.ratio_9:16.i2v"), parent_span, depth, elapsed_ms (on close). Keep overhead minimal.
```

## Verify
`tests/test_spans.py`: two nested `@span` async fns produce JSON logs whose `span` paths nest correctly and include `elapsed_ms`.

# 10 — fal.ai Async Client (queue submit/poll · retries · bounded concurrency)

## Call path with backpressure

```
 caller (pipeline tool)
      │ acquire ──▶ asyncio.Semaphore(MAX_FAL_CONCURRENCY)   ◀ caps real load on fal
      ▼
 submit_and_wait(model_id, args)
      │ POST fal queue ──▶ request_id
      ▼
 ┌────────── poll loop (exp backoff + jitter) ──────────┐
 │ status? IN_QUEUE → IN_PROGRESS → COMPLETED / FAILED   │
 └───────────────────────────────────────────────────────┘
      │ COMPLETED ▶ result payload      FAILED/5xx/network ▶ tenacity retry (max 3)
      ▼                                  4xx validation ▶ raise (no retry)
   release semaphore
```

## Retry decision tree

```
 error?
  ├─ network / timeout / 5xx / queue-error ─▶ retry (exp backoff, jitter, ≤3)
  ├─ 4xx (bad args)                          ─▶ raise immediately
  └─ none                                     ─▶ return result
```

## Prompt

```
app/providers/fal_client.py — async wrapper over fal's QUEUE API (fal-client async or httpx).
- Module-level asyncio.Semaphore(settings.max_fal_concurrency), acquired around EVERY fal call.
- async submit_and_wait(model_id, arguments) -> dict: submit to fal queue, poll status with
  exponential backoff + jitter until COMPLETED/FAILED, return result. Log request_id + queue
  position. Wrap in obs @span("fal." + model_id).
- tenacity retry: max 3 attempts, exponential backoff w/ jitter, ONLY on transient (network/5xx/
  queue) errors; never retry 4xx.
- Typed helpers mapping to config MODEL_REGISTRY:
    run_upscale(image_url, factor)
    run_outpaint(image_url, target_w, target_h)
    run_image_to_video(image_url, prompt, duration_seconds, aspect_ratio)
- Single shared httpx.AsyncClient. Read FAL_KEY from settings.
Add TODO comments to confirm exact argument field names on the live model API pages
(Clarity Upscaler, FLUX 2 Pro Outpaint, Seedance 2 image-to-video) before finalizing.
```

## Verify
With a real `FAL_KEY`, a script calling `run_upscale` on a sample image returns a result URL; unit test mocks the queue and asserts retry skips 4xx.

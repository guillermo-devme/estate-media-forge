---
inclusion: always
---

# Product

Real-estate media-kit platform. A property photo becomes a 3-aspect-ratio media kit
(1:1, 9:16, 16:9) through **upscale → expand/outpaint → cinematic image-to-video**, powered by
**fal.ai** and orchestrated with **LangGraph**.

## Two codebases, one product

- **FastAPI service** (`kiro-prompts/` build plan): async compute backend. Receives signed
  server-to-server calls, runs the AI pipeline, returns media URLs. Owns NO money/balance.
- **Wix Studio / Velo site** (`wix-site/`): the front end + auth + roles + **token balance of
  record** (Wix CMS). Stripe is the only path that adds tokens; only the owning member may spend.

## Non-negotiables

- Users see **credits**, never USD. Pricing math (provider cost × 3.2 earnings ÷ peg) stays on the
  server and is never serialized to clients.
- Only the **authenticated owning member** can spend their tokens.
- Only **Stripe webhooks** (via Wix http-function) can add tokens.
- Every external call is **bounded, observable, and idempotent**.
- No deployment infrastructure is assumed yet — do not add Docker/cloud/k8s unless asked.

# 02 — Configuration & Swappable Model Registry

## Config resolution flow

```
 .env / environment
        │  pydantic-settings (BaseSettings)
        ▼
 ┌─────────────────────────────────────────────┐
 │ Settings (lru_cache get_settings())          │
 │  api_keys_json ──parse──▶ {api_key: tenant}  │
 │  fal_key, redis_url, ledger_dsn              │
 │  media_dir, public_base_url                  │
 │  max_fal_concurrency, max_queue_depth        │
 │  earnings_ratio=3.2, credit_peg_usd=0.01     │
 │  hold_ttl_seconds=900                         │
 │  MODEL_REGISTRY{upscale,outpaint,i2v}        │
 │  RATIO_DIMS{1:1,9:16,16:9}                   │
 └─────────────────────────────────────────────┘
        │ env overrides
        ▼
 FAL_MODEL_UPSCALE / FAL_MODEL_OUTPAINT / FAL_MODEL_I2V  swap models w/o code change
```

## Prompt

```
Implement app/config.py with pydantic-settings BaseSettings reading env/.env:
- service_key (FASTAPI_SERVICE_KEY), service_hmac_secret (SERVICE_HMAC_SECRET),
  wix_refund_url (WIX_REFUND_URL) — the Wix→API trust + refund callback.
- fal_key, redis_url (default redis://localhost:6379), ledger_dsn
  (default sqlite+aiosqlite:///./usage.db), media_dir (default "media"),
  public_base_url (default http://localhost:8000), max_fal_concurrency (int, 8),
  max_queue_depth (int, 500), earnings_ratio (float, 3.2), credit_peg_usd (float, 0.01),
  log_level ("INFO"), langsmith_api_key (optional),
  langsmith_project ("realestate-media"), langchain_tracing_v2 (bool, True).

MODEL_REGISTRY dict (stage -> fal endpoint id), each env-overridable:
  upscale  -> "fal-ai/clarity-upscaler"        (FAL_MODEL_UPSCALE)
  outpaint -> "fal-ai/flux-2-pro/outpaint"      (FAL_MODEL_OUTPAINT)
  i2v      -> "fal-ai/bytedance/seedance-2.0/image-to-video" (FAL_MODEL_I2V)

RATIO_DIMS: "1:1"->(1080,1080), "9:16"->(1080,1920), "16:9"->(1920,1080).
Expose cached get_settings() (lru_cache). (No tenant/api-key map — auth is service key + HMAC, 06.)

⚠️ HARD GATE — the three model ids above are UNVERIFIED placeholders. Before writing them as the
defaults you MUST confirm each against the live fal.ai docs / model pages (or ask the operator to
paste the current endpoint id). For each of upscale / outpaint / i2v confirm: (a) the exact endpoint
id string, and (b) that the model still exists and is GA (not deprecated/renamed). If you cannot
verify a given id, do NOT silently guess — keep it env-overridable and put a
`# UNVERIFIED: confirm endpoint id on fal docs before production` comment on that line so it surfaces
in review. The entire pipeline is dead if any id is wrong, so this is not optional.
```

## Verify
`python -c "from app.config import get_settings; print(get_settings().MODEL_REGISTRY, get_settings().earnings_ratio)"` prints the registry and `3.2`. **Also confirm** no `MODEL_REGISTRY` value still carries an `# UNVERIFIED` comment by the time prompt 10 is built — each must be checked against fal docs first.

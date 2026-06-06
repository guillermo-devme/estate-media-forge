# 01 — Project Scaffold & Tooling

## Folder dependency graph this prompt creates

```
realestate-media-api/
├── pyproject.toml ── deps: fastapi, pydantic, arq, redis, httpx, fal-client,
│                           langgraph, langchain, langsmith, sqlalchemy, aiosqlite,
│                           python-json-logger, tenacity
├── .env.example
├── app/
│   ├── main.py ──────────── FastAPI() factory (placeholder root)
│   ├── config.py            (02)        deps.py (06)
│   ├── pricing.py (03)
│   ├── schemas/  (04)        obs/ (05)
│   ├── providers/ (10)       pipeline/ (11)
│   ├── wallet/   (07,08,09)  jobs/ (12)
│   └── routers/  (13,14)
├── media/        (served static, gitignored)
└── tests/postman/
```

## Prompt

```
Create a Python 3.11 project "realestate-media-api" with pyproject.toml (PEP 621). Dependencies:
fastapi, uvicorn[standard], pydantic>=2, pydantic-settings, arq, redis, httpx, fal-client,
langgraph, langchain, langchain-core, langsmith, sqlalchemy>=2, aiosqlite, python-json-logger,
tenacity. Dev: pytest, pytest-asyncio, ruff, anyio.

Create this tree with empty/stub files:
app/main.py, app/config.py, app/pricing.py, app/deps.py,
app/schemas/{__init__,enums,requests,responses}.py,
app/obs/{__init__,logging,spans}.py,
app/providers/{__init__,fal_client,wix_client}.py,
app/pipeline/{__init__,tools,state,graph}.py,
app/wallet/{__init__,models,repository,quotation}.py,   # usage/audit ledger + pricing only
app/jobs/{__init__,store,worker,enqueue}.py,
app/routers/{__init__,health,media_kit,upscale,video,jobs,quotation,metrics}.py,
media/.gitkeep, tests/postman/.gitkeep, tests/__init__.py.

.env.example keys: FASTAPI_SERVICE_KEY (shared static key, Wix→API), SERVICE_HMAC_SECRET (shared
HMAC secret, both directions), WIX_REFUND_URL (Wix /_functions/falRefund), FAL_KEY, REDIS_URL,
LEDGER_DSN (default sqlite+aiosqlite:///./usage.db), MEDIA_DIR, PUBLIC_BASE_URL,
MAX_FAL_CONCURRENCY, MAX_QUEUE_DEPTH, EARNINGS_RATIO (default 3.2), CREDIT_PEG_USD (default 0.01),
LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGCHAIN_TRACING_V2, LOG_LEVEL.
(Balance/wallet/Stripe live in Wix, not here — see ../wix-integration.)

README with placeholder "Run locally". .gitignore ignores media/, *.db, .env, __pycache__, .venv.
NO Docker / cloud / CI / deploy files. app/main.py = minimal FastAPI() with a placeholder root
route so `uvicorn app.main:app` imports cleanly.
```

## Verify
`pip install -e .` succeeds and `uvicorn app.main:app` boots without import errors.

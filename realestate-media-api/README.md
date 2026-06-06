# realestate-media-api

Async compute backend that turns a property photo into a 3-aspect-ratio media kit
(1:1, 9:16, 16:9) via **upscale → expand/outpaint → cinematic image-to-video**, powered by
**fal.ai** and orchestrated with **LangGraph**.

This service is a **server-to-server compute backend** fronted by a Wix Studio (Velo) site.
Wix owns member auth, roles, and the **token balance of record** (Wix CMS). This service owns
**no money/balance** — it keeps an append-only usage/audit ledger only. See
`../docs/wix-integration/INDEX.md` for the cross-system flow.

## Run locally

```bash
# 1. Create and activate a virtualenv
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install (editable) with dev tools
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env   # then fill in values

# 4. Boot the API
uvicorn app.main:app --reload
```

Open http://localhost:8000 — interactive docs land at `/docs` (Swagger) and `/redoc` once routers
are wired up in later prompts.

> **Scope:** this is a local, single-host demo. Deployment (HTTPS host, ingress lock to Wix egress,
> Redis persistence, durable media storage, Postgres ledger) is intentionally out of scope for the
> initial build — see `../docs/kiro-prompts/INDEX.md` for the durability checklist.

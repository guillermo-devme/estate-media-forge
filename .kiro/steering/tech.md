---
inclusion: manual
---

<!-- Pull this in on demand with #tech when you need the stack/versions reference.
     Kept out of always-on context to save budget; the active rails are product, structure,
     security (always), plus python-fastapi / velo-wix / testing / dependency-safety (conditional). -->

# Tech Stack

## FastAPI service
- **Python 3.11+**, **FastAPI**, **Pydantic v2** (schema contracts; zod-equivalent).
- **ARQ + Redis** for async jobs (API returns `202` immediately; workers do the heavy lifting).
- **LangGraph `StateGraph`** is the pipeline engine; fal calls wrapped as **LangChain tools**.
- **fal.ai** queue API (config-swappable model registry: Clarity Upscaler / FLUX 2 Pro Outpaint /
  Seedance 2).
- Observability: **structured JSON logs (Google Cloud Logging-compatible)** + a nested
  **span/timer** decorator + **LangSmith** token/cost tracing.
- Auth: **static service key + HMAC-signed body** (Wix is the only caller).
- Docs: built-in **Swagger `/docs` + ReDoc `/redoc`**.
- Audit ledger only: pluggable repo, default **SQLite** (SQLAlchemy 2.0 async). Balance lives in Wix.

## Wix / Velo
- **Velo web methods** (`.web.js`, `webMethod(Permissions.SiteMember, …)`), `http-functions.js`,
  `wix-members-backend`, `wix-data`, `wix-secrets-backend`, `wix-fetch`, Node `crypto`.

## Tooling expectations
- Package manager: **uv** or **pip** with a committed lockfile. Node uses **npm** with
  `package-lock.json`.
- Lint/format: **ruff** (Python). Type checks where practical.
- Tests: **pytest + pytest-asyncio**. Mock fal and Redis in unit tests.
- Never introduce a new dependency without the dependency-safety checks (see dependency-safety.md).

## Versions
When unsure about a library/API's current shape, consult the **Wix MCP** (Velo APIs) or do a quick
check rather than guessing — Velo and fal APIs evolve.

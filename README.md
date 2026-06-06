# Real-Estate Media-Kit Platform

AI media-kit service for real-estate: a property photo becomes a 3-aspect-ratio kit
(1:1, 9:16, 16:9) via **fal.ai** (upscale → expand/outpaint → cinematic image-to-video),
orchestrated with **LangGraph**, fronted by **Wix Studio (Velo)** for auth, roles, and a
token wallet (Stripe-funded credits).

## Where things live

- `docs/IDE_CONFIG.md` — Kiro steering, hooks and MCP server setup.
- `docs/kiro-prompts/` — ordered build prompts for the FastAPI service (start at `INDEX.md`).
- `docs/wix-integration/` — Wix/Velo architecture + setup guide (`SETUP.md`).
- `docs/wix-site/` — the Velo project to paste into Wix (`/backend /pages /public`).
- `.kiro/` — IDE config (steering, hooks, `settings/mcp.json`). It lives at the **repository
  root**, so open the **repo root** (this folder) as the Kiro workspace — NOT `docs/`. Kiro loads
  `.kiro/` only from the workspace root; opening `docs/` would silently disable every steering
  rule and hook. All prompts and docs are under `docs/`; the generated FastAPI project
  (`realestate-media-api/`) is created at the repo root by `docs/kiro-prompts/01-scaffold.md`.

> ⚠️ **Path consistency note for Kiro:** because the workspace root is the repo root, every path a
> steering file or prompt references is relative to the repo root: prompts are at
> `docs/kiro-prompts/`, the Velo project at `docs/wix-site/`, the Wix docs at `docs/wix-integration/`.
> The conditional steering `velo-wix.md` matches `docs/wix-site/**`.

## Deployment / runtime status

No deployment infrastructure is committed — that decision is **deferred**, which means the system
as specified runs **locally only** (`FASTAPI_BASE_URL=http://localhost:8000`). Before this can serve
a live Wix site you must add: a reachable HTTPS host for FastAPI with ingress locked to Wix egress
IPs, Redis **persistence** (AOF/RDB — job state + the ARQ queue both live in Redis), durable storage
for generated media (object storage, not the local `media/` dir), and a backup/rotation story for
the SQLite usage ledger. See `docs/kiro-prompts/INDEX.md` → "Durability & deployment scope".

# IDE Config — Kiro Steering, Hooks & MCP Servers

This file documents the `.kiro/` configuration that keeps both codebases (the FastAPI service and
the Wix/Velo site) on the rails: best practices, well-tested, no secret leaks, no compromised
packages, and clean GitHub + Wix integrations. Everything here is already written into the repo —
this doc explains what each piece does and how to activate it in Kiro.

> ⚠️ **Open the repository root as the Kiro workspace** (the folder that contains `.kiro/`), NOT
> `docs/`. Kiro loads `.kiro/` only from the workspace root. If you open `docs/` instead, `.kiro/`
> sits one level above the workspace and **none of the steering or hooks below take effect** — the
> build loses every guardrail. All prompts/docs are under `docs/`; conditional steering paths are
> relative to the repo root (e.g. `docs/wix-site/**`).

```
.kiro/
├── steering/        rules Kiro reads — always / conditionally / on demand (tuned for context cost)
│   ├── product.md            (always)                  ← what we're building (orientation)
│   ├── structure.md          (always)                  ← repo boundaries (must always hold)
│   ├── security.md           (always)                  ← money/auth rails — never skipped
│   ├── tech.md               (manual: #tech)           ← stack reference, pull when needed
│   ├── git-github.md         (manual: #git-github)     ← commit/PR rules (action-triggered)
│   ├── dependency-safety.md  (fileMatch **/pyproject.toml)
│   ├── testing.md            (fileMatch **/*.py)
│   ├── python-fastapi.md     (fileMatch **/*.py)
│   └── velo-wix.md           (fileMatch docs/wix-site/**)
├── hooks/           event-driven automations (run on save)
│   ├── python-tests-and-lint.kiro.hook
│   ├── dependency-audit.kiro.hook
│   ├── secret-leak-guard.kiro.hook
│   ├── security-review.kiro.hook
│   └── velo-wallet-review.kiro.hook
└── settings/
    └── mcp.json     MCP servers: github, wix, semgrep, filesystem
.gitignore           keeps secrets out of git
```

---

## How the pieces work together

```
        ┌──────────────── STEERING (the "rules") ────────────────┐
        │ always-on (lean): product, structure, security          │
        │ conditional: python-fastapi + testing (*.py),           │
        │   dependency-safety (pyproject.toml), velo-wix (wix-site)│
        │ manual: #tech, #git-github  (pull on demand)            │
        └───────────────────────────┬────────────────────────────┘
                                     │ inform every generation
            you edit a file ─────────▼──────────── HOOKS (the "reflexes")
                save ──▶ python-tests-and-lint   → ruff + pytest, fix failures
                save ──▶ secret-leak-guard       → block hardcoded secrets
                save ──▶ security-review         → vuln-class review (+ Semgrep MCP)
                save ──▶ velo-wallet-review      → authz/idempotency on Wix code
           edit manifest ──▶ dependency-audit    → typosquat check + pip/npm audit
                                     │ may consult
                                     ▼
                            MCP SERVERS (the "reach")
              github (read PRs/issues/CI) · wix (Velo docs + APIs)
              semgrep (security scan)     · filesystem (scoped, off by default)
```

---

## 1. Steering files — what each enforces

| File | Inclusion | Purpose |
|---|---|---|
| `product.md` | always | What we're building; the two-codebase split; the credits/Stripe/member non-negotiables. |
| `structure.md` | always | Repo layout and the **hard boundaries** (Wix ≠ Python imports; money only in Wix; secrets never in code). |
| `security.md` | always | Auth/authz/money rules, secret handling, input/SSRF/injection, output safety, default-deny posture. Kept always-on by design — safety rails for a money system are never traded for context budget. |
| `tech.md` | manual `#tech` | The exact stack (FastAPI/Pydantic/ARQ/LangGraph/fal; Velo) and tooling. Reference material — pull in when you need versions/choices. |
| `git-github.md` | manual `#git-github` | Commit/PR conventions, never commit secrets, read-only MCP by default. Triggered by an action (commit/PR), not a file type. |
| `dependency-safety.md` | fileMatch `**/pyproject.toml` | No typosquats/compromised packages; pin + lock; audit on every manifest change. Loads when editing the Python manifest; pull with `#dependency-safety` for other manifests. |
| `testing.md` | fileMatch `**/*.py` | What must be tested (money/auth/external I/O), mocking externals, the bar to merge. Loads with the Python code it governs. |
| `python-fastapi.md` | fileMatch `**/*.py` | Async correctness, Pydantic at boundaries, `Decimal` money, span logging, idempotent external calls. |
| `velo-wix.md` | fileMatch `docs/wix-site/**` | Web-method auth/role gating, balance only via the per-member lock, idempotency, minimal elevation. |

> **Inclusion modes & context budget.** `always` is read on every interaction (keep this set small —
> only `product`, `structure`, `security`). `fileMatch` is read only when a matching file is in
> context, so per-language/per-area rules load just-in-time. `manual` files cost nothing until you
> pull them with `#steering-file-name`. This trims the always-on steering from ~1.6k words to ~0.77k
> per turn while keeping the non-negotiable rails (product grounding, structural boundaries, security)
> always present. Trade-off to know: `fileMatch`/`manual` rules are silently absent when their
> trigger isn't met — so anything truly cross-cutting and high-stakes (here: security) stays `always`.

## 2. Hooks — what each does on save

| Hook | Trigger | Action |
|---|---|---|
| `python-tests-and-lint` | save `**/*.py` | Run ruff + the relevant pytest; fix failures without weakening assertions. |
| `dependency-audit` | save `pyproject.toml` / `requirements*.txt` / `uv.lock` / `package.json` / `package-lock.json` | Verify each new package is the canonical, non-typosquatted name; run `pip-audit` / `npm audit`; block on criticals or unverified packages. |
| `secret-leak-guard` | save code/json/env/md | Scan the diff for hardcoded keys/tokens/secrets; if found, tell you to rotate + move to env/Secrets Manager + gitignore. |
| `security-review` | save routers/providers/deps/jobs `*.py` + `wix-site/backend/**` | Review for auth gaps, broken idempotency, SSRF, injection, unbounded calls, leaked cost/stack traces (uses Semgrep MCP if present). |
| `velo-wallet-review` | save `wix-site/backend/**` | Verify currentMember+assertRole before side effects, lock-protected balance, tx idempotency, signature checks on inbound HTTP. |

> Hooks are editable JSON. Set `"enabled": false` to mute one. They run an agent prompt
> (`then.type: askAgent`); you can swap any to a shell command with `then.type: runCommand` if you
> prefer a deterministic script (e.g. literally invoking `ruff` / `pytest` / `pip-audit`).

## 3. MCP servers (`.kiro/settings/mcp.json`)

| Server | Transport | Use | Notes |
|---|---|---|---|
| **github** | stdio (Docker, official `ghcr.io/github/github-mcp-server`) | Read PRs/issues/CI status, open PRs | `autoApprove` lists **read-only** tools only; writes (merge/release) need manual approval. |
| **wix** | remote (`https://mcp.wix.com/mcp`) | Search Velo/Wix docs, write Velo code, call Wix APIs | Keeps the Velo code aligned with current Wix APIs (avoids guessing). |
| **semgrep** | stdio (`uvx semgrep-mcp`) | Security scanning for the `security-review` hook | Powers vulnerability-class detection. |
| **filesystem** | stdio (`@modelcontextprotocol/server-filesystem`) | Scoped file access | **Disabled by default**; enable + set the absolute repo path only if you want it. |

### Activation steps

1. **GitHub MCP**
   - Create a **fine-grained PAT** with the *minimum* scopes (read-only on the repos you need;
     add write only if you truly want Kiro opening PRs). Prefer read-mostly.
   - Provide it as the env var `GITHUB_PERSONAL_ACCESS_TOKEN` (the config references
     `${GITHUB_PERSONAL_ACCESS_TOKEN}` so the token is **not** written into the file). Requires
     Docker running locally. (Alternative: the remote server `https://api.githubcopilot.com/mcp/`
     with a Bearer PAT — swap the `github` block to a `"url"` form if you prefer no Docker.)
2. **Wix MCP** — no key needed to start; it will prompt for auth when you call account/site tools.
3. **Semgrep MCP** — needs `uv`/`uvx` installed; first run downloads `semgrep-mcp`.
4. **filesystem** — flip `"disabled": false` and replace `/ABSOLUTE/PATH/TO/Real-state-media`.
5. Reload MCP servers in Kiro (MCP panel → reconnect) after editing `mcp.json`.

> **Security:** if you ever hardcode a token in `mcp.json`, gitignore it (the line is pre-staged in
> `.gitignore`). Keep `autoApprove` limited to read-only tools so no destructive action runs
> unattended. Treat every committed secret as compromised — rotate, don't just delete.

---

## Quick start

1. Open the `Real-state-media` folder in Kiro (the `.kiro/` config loads automatically).
2. Set `GITHUB_PERSONAL_ACCESS_TOKEN` in your environment; ensure Docker + `uv` are installed.
3. Reload MCP servers; confirm `github`, `wix`, `semgrep` connect.
4. Start building from `kiro-prompts/INDEX.md` (FastAPI) — steering + hooks now apply to every edit.
5. For the Wix side, build/paste from `wix-site/` per `wix-integration/SETUP.md`.

Sources: [Kiro steering](https://kiro.dev/docs/steering/), [Kiro hooks](https://kiro.dev/docs/hooks/), [Kiro MCP on AWS re:Post](https://repost.aws/articles/ARuX8rkojgSx-TYCc65JyAOw/getting-started-with-kiro-and-mcp-servers-connect-your-ai-ide-to-real-world-tools), [GitHub MCP server](https://github.com/github/github-mcp-server), [Wix MCP](https://dev.wix.com/docs/sdk/articles/use-the-wix-mcp/about-the-wix-mcp)

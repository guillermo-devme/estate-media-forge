---
inclusion: manual
---

<!-- Pull this in with #git-github before committing / opening a PR. The trigger is an action,
     not a file type, so it's manual rather than always-on (saves context every other turn). -->

# Git & GitHub Workflow

- **Never commit secrets.** Ensure `.env`, `*.db`, `media/`, and any `mcp.json` containing a token
  are gitignored. If a secret is ever committed, treat it as compromised: rotate it, don't just
  delete the line.
- **Small, focused commits** with imperative messages (e.g. "add HMAC verification to submit
  endpoints"). Conventional Commits style is welcome (`feat:`, `fix:`, `test:`, `chore:`).
- **Branch per change**; open a PR. PR description states: what changed, why, tests added, and—if
  it touches auth/money/external I/O—the security threat considered and its mitigation.
- **Definition of done before merge**: tests pass, ruff/lint clean, dependency audit clean for any
  manifest change, no new secrets, docs/steering updated if behavior changed.
- Use the **GitHub MCP** for reading PRs/issues/CI status and opening PRs. Prefer **read-only** MCP
  operations; any write (merge, release, branch protection change) requires explicit human approval.
- Recommend repo hygiene: branch protection on the default branch, required status checks
  (tests + audit), and required review for changes to auth/payment code.

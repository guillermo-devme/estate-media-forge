---
inclusion: fileMatch
fileMatchPattern: "docs/wix-site/**"
---

# Velo / Wix Conventions

- **Web methods** use `webMethod(Permissions.SiteMember, …)` from `wix-web-module`. Every spend or
  wallet method must start by resolving `currentMember.getMember()` and `getRoles()`, then
  `assertRole(service, roles)` BEFORE any side effect. Anonymous → reject.
- **Balance authority is Wix CMS.** Only `backend/lib/wallet.js` mutates balance, always inside the
  per-member lock (`TokenLocks` unique-`_id` insert — Wix has no atomic increment/locking).
- **Idempotency** via `TokenTransactions._id`: `stripe_{eventId}`, `spend_{ref}`, `refund_{jobId}`,
  `adjust_{uuid}`. Insert the tx row as the idempotency claim, then update balance.
- **Elevation/`suppressAuth`** is used only in backend lib modules for CMS access, with the
  narrowest scope. Never expose an elevated/unauthenticated path to the frontend that can spend or
  read another member's data.
- **Secrets** come from `wix-secrets-backend` (`getSecret`) — never hardcoded. Outbound calls to
  FastAPI go through `lib/falClient.js` (HMAC-signed). Inbound `http-functions.js` must verify
  signatures (Stripe signature for the webhook; service-key + HMAC for the refund callback) before
  doing anything.
- **CMS collections are Admin-only**; all reads/writes go through elevated backend modules. The
  frontend never touches collections directly.
- Keep `/backend /pages /public` boundaries: `lib/*` internal, `*.web.js` the only callable surface,
  `public/*` shared frontend helpers (no secrets, no privileged logic).
- Validate all inbound params; treat client URLs/prompts as untrusted (SSRF-aware).

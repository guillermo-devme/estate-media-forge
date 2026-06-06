---
inclusion: always
---

# Security Rules (enforce on every change)

## Identity, authz, money
- The FastAPI side trusts a request ONLY after full HMAC verification: service-key match, timestamp
  skew ≤ 300s, **unseen nonce** (replay protection), valid signature over
  `${ts}.${nonce}.${member_id}.${sha256(body)}`, and header `member_id` == body `member_id`.
- A member may only ever act on **their own** `member_id`. Reject/return 404 on any cross-member
  access (jobs, wallet). No enumeration.
- Token grants happen ONLY via the Stripe webhook http-function, verified with the Stripe signature
  and idempotent on the Stripe event id. No other code path may increase a balance (except the
  admin-only manual adjust, which is role-gated and audited).
- Spends/refunds are idempotent (`spend_{ref}`, `refund_{jobId}`) and serialized per member.

## Secrets
- Never hardcode keys, tokens, PATs, or webhook secrets. Use Wix Secrets Manager (Velo) and `.env`
  (FastAPI, gitignored). `.kiro/settings/mcp.json` must be gitignored if it contains a token.
- Never log secrets, full tokens, signatures, or raw request bodies containing PII.

## Input & web safety
- Validate every external input with Pydantic (FastAPI) / explicit checks (Velo). Treat all
  client-supplied URLs and prompts as untrusted.
- Guard against SSRF when fetching user-supplied image URLs (allowlist schemes/hosts as feasible;
  no internal/metadata addresses).
- No raw string SQL; use the ORM/parameterized queries. No `eval`, no unsafe deserialization
  (`pickle` on untrusted data, `yaml.load` without SafeLoader).
- fal/Redis/Wix calls: bounded concurrency, timeouts, retries with backoff on transient errors only.

## Output
- Responses contain **credits, never USD or internal cost**. Never leak stack traces to clients;
  return structured errors and log details server-side.

## Posture
- Default-deny. When a change touches auth, money, or external I/O, call out the threat considered
  and how it's mitigated in the PR description.
- Lock FastAPI ingress to the Wix egress range; rotate the service key + HMAC secret periodically.
- Migration path: per-request signed JWTs (member claim) replace the static key with no endpoint
  changes — prefer this when feasible.

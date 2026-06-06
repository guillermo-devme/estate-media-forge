# 06 — Service Auth (HMAC) + Member Identity

> **Changed for the Wix model.** The only caller is the Wix Velo backend (server-to-server). Wix
> already authenticated the member and checked roles. Our API verifies the **service key + HMAC**
> and trusts the `member_id` it carries. There are no per-end-user API keys here.

## Verification pipeline

```
 request from Wix .web.js
   headers: X-Service-Key, X-Member-Id, X-Member-Role, X-Timestamp, X-Nonce, X-Signature
   body: {..., member_id}
        │
        ▼
 1 X-Service-Key == settings.service_key ?            no ─▶ 401
 2 |now − X-Timestamp| ≤ 300s ?                       no ─▶ 401 (stale/replay)
 3 X-Nonce unseen ? (Redis SETNX, TTL 600s)           no ─▶ 401 (replay)
 4 sig == HMAC_SHA256(secret, `${ts}.${nonce}.${member_id}.${sha256(rawBody)}`) ? no ─▶ 401
 5 X-Member-Id == body.member_id ?                    no ─▶ 401 (identity mismatch)
        │ all pass
        ▼
 AuthContext{ member_id, role }  ──▶ bound to log context, injected into routers
```

## Why each check exists

```
 service key   → only Wix can call us
 timestamp     → bounds replay window
 nonce         → blocks replay within the window
 HMAC over body→ body can't be tampered (can't swap member_id or params)
 id match      → the signed member_id is the spender; no spoofing another member
```

## Prompt

```
Implement app/deps.py for server-to-server HMAC auth (single caller = Wix backend):
- Settings: service_key, service_hmac_secret (add to config.py + .env: FASTAPI_SERVICE_KEY,
  SERVICE_HMAC_SECRET, plus WIX_REFUND_URL for the worker).
- Dependency verify_service_request(request): read raw body once; verify in order: X-Service-Key
  (constant-time), timestamp skew ≤ 300s, nonce unseen via Redis SETNX (TTL 600s),
  signature == HMAC_SHA256(secret, f"{ts}.{nonce}.{member_id}.{sha256_hex(raw_body)}"),
  and X-Member-Id == body's member_id. Any failure → 401 with a generic message.
- Return AuthContext{member_id, role}. Provide Annotated alias `Auth`. Bind member_id into the
  obs logging context.
- IMPORTANT: read the raw body for both signature verification AND Pydantic parsing without
  consuming the stream twice (cache request body).
Unit tests: tampered body → 401; reused nonce → 401; skewed timestamp → 401; member_id mismatch
→ 401; valid signed request → AuthContext.
Add a short comment: this is the static-key+HMAC model; swapping to JWT verification later only
changes this dependency.
```

## Verify
A signed request (matching `wix-integration/velo/backend/lib/falClient.js`) passes; flipping any byte of body, key, or member_id yields 401; replaying a nonce yields 401.

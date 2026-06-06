# 15 — OpenAPI / Swagger / ReDoc Polish

> **Changed for the Wix model.** Security scheme documents the **HMAC service headers** (not an
> end-user API key). The lifecycle shown is the cross-system quote→decrement(Wix)→submit→poll→
> refund flow.

## Docs surface

```
 /docs        Swagger UI   ── Authorize(service headers) · enum dropdowns · examples
 /redoc       ReDoc        ── same schema, reference layout
 /openapi.json raw schema
        │
        ▼
 tags: quotation · pricing · media-kit · upscale · video · jobs · metrics · health
 description (markdown): credits model + Wix-fronted lifecycle
```

## Documented lifecycle (shown in the docs description)

```
 Wix quote ─▶ Wix decrement (the hold) ─▶ submit(member_id,client_ref,quoted_credits) ─▶ 202
        ─▶ poll ─▶ completed                      └─ partial/failed ─▶ worker refunds → Wix
```

## Prompt

```
Enhance docs using FastAPI built-ins (no heavy deps):
- Enable Swagger /docs + ReDoc /redoc with title, summary, version, and a markdown description
  explaining: the credits model (credits only, USD never leaves the server), that Wix owns the
  balance + auth, and the quote→decrement(Wix)→submit→poll→refund lifecycle. Paste the lifecycle
  ASCII into the description.
- Document the service auth as an ApiKey-style security scheme over the HMAC headers
  (X-Service-Key, X-Member-Id, X-Timestamp, X-Nonce, X-Signature) shown in Authorize and applied to
  protected routes. (Real verification is the HMAC dependency from prompt 06.)
- All enums (AspectRatio, ServiceType, JobStatus, FalStage) render allowed values. Add tags +
  per-endpoint summaries/descriptions + request/response examples (from json_schema_extra). Expose
  /openapi.json. Add a custom openapi() injecting a short "How quotation + polling works (Wix
  fronts auth + balance)" section.
```

## Verify
`/docs` shows all tags, the HMAC header fields in Authorize, enum dropdowns, and examples; the description renders the lifecycle diagram; `/redoc` matches.

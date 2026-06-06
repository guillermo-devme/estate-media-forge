# 04 — Schema Contracts & Enums (Pydantic = our zod)

> **Changed for the Wix model.** Submit requests carry `member_id`, `client_ref`, and
> `quoted_credits` (set by the Wix backend after it decremented the wallet). There is no `quote_id`/
> hold here, no wallet/top-up schemas (Wix owns balance). Quotation is pure pricing.

## Contract map

```
 ENUMS
 ┌──────────────────────────────────────────────────────────────┐
 │ AspectRatio  : 1:1 | 9:16 | 16:9                               │
 │ ServiceType  : upscale | media_kit | image_to_video            │
 │ JobStatus    : queued|running|partial|completed|failed         │
 │ FalStage     : upscale | outpaint | i2v                        │
 └──────────────────────────────────────────────────────────────┘

 REQUESTS (carry member_id + client_ref + quoted_credits)     RESPONSES
 ┌───────────────────────────┐   ┌──────────────────────────┐
 │ UpscaleRequest             │   │ QuotationResponse         │ (credits + breakdown only)
 │ ImageToVideoRequest        │──▶│ JobAccepted               │ (job_id, quoted_credits, poll_url)
 │ MediaKitRequest            │   │ JobStatusResponse         │ (status, assets, quoted/refunded)
 │ QuotationRequest (pricing) │   │ AllowanceResponse         │ (counts from a passed balance)
 └───────────────────────────┘   └──────────────────────────┘
```

## Prompt

```
app/schemas/enums.py — str Enums: AspectRatio("1:1","9:16","16:9"),
ServiceType("upscale","media_kit","image_to_video"),
JobStatus("queued","running","partial","completed","failed"),
FalStage("upscale","outpaint","i2v").

app/schemas/requests.py (Pydantic v2, Field descriptions + json_schema_extra examples + validators).
Shared mixin SignedActor: member_id(str). Submit requests also: client_ref(str), quoted_credits(int).
- UpscaleRequest(SignedActor): image_url(HttpUrl), aspect_ratios(list[AspectRatio]=all 3),
  upscale_factor(int 2..4=2), client_ref(str), quoted_credits(int).
- ImageToVideoRequest(SignedActor): image_url, room_name(str), aspect_ratios(=all 3),
  duration_seconds(int 3..10=5), prompt_override(optional), client_ref, quoted_credits.
  Computed default cinematic prompt filling room_name:
  "Create a 3d walkthrough animation of this property room: {room_name}. Add soft, clean elegant
   lighting and smooth camera movements. Follow the same layout of this image precisely and
   maintain strict architectural consistency throughout the cinematic sequence."
- MediaKitRequest(SignedActor): image_url, room_name, aspect_ratios(=all 3), do_expand(bool=True),
  upscale_factor(int 2..4=2), duration_seconds(int 3..10=5), prompt_override(optional),
  client_ref, quoted_credits.
- QuotationRequest(SignedActor): service(ServiceType) + union of params (image_url, room_name opt,
  aspect_ratios, duration_seconds, do_expand, upscale_factor, images:int=1). Validate per service.
- AllowanceRequest(SignedActor): balance(int).

app/schemas/responses.py:
- QuoteBreakdownItem: stage(FalStage), quantity(number), credits(int)  # NO usd field, ever.
- QuotationResponse: service, total_credits(int), breakdown(list[QuoteBreakdownItem]).
- AllowanceResponse: allowance(dict[str,int]).
- AssetSet: aspect_ratio, upscaled_url(opt), expanded_url(opt), video_url(opt), status(JobStatus),
  error(opt).
- JobAccepted: job_id, status(JobStatus), service, poll_url, quoted_credits(int).
- JobStatusResponse: job_id, member_id, service, status, created_at, updated_at,
  assets(list[AssetSet]), quoted_credits(int), refunded_credits(int), token_usage(opt dict), error(opt).

Every model gets json_schema_extra examples. No schema may contain a USD/price or balance field —
credits only, and balance lives in Wix.
```

## Verify
`QuotationResponse.model_json_schema()` shows credits + breakdown and **no USD/balance**; submit requests require `member_id`, `client_ref`, `quoted_credits`; enums render allowed values.

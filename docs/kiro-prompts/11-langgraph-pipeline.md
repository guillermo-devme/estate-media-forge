# 11 — LangGraph Pipeline (StateGraph engine · LangChain tools · LangSmith)

The per-aspect-ratio engine. fal calls are LangChain tools so LangSmith captures token/cost/timing.

## StateGraph (one ratio)

```
        PipelineState{job_id, aspect_ratio, room_name, source_image_url, ...}
                              │
                          ┌───▼────┐  upscale_tool ─▶ fal.clarity
                          │upscale │  sets upscaled_url
                          └───┬────┘
                  do_expand?  │
              ┌──── yes ──────┤───── no ─────┐
              ▼               │              │ (passthrough: expanded_url = upscaled_url)
          ┌────────┐          │              │
          │ expand │ outpaint_tool ─▶ fal.flux-2 (to RATIO_DIMS[w,h])
          └───┬────┘          │              │
              └───────────────┤◀─────────────┘
                          ┌───▼────┐  i2v_tool ─▶ fal.seedance-2
                          │  i2v   │  cinematic prompt + ratio + duration
                          └───┬────┘  sets video_url
                              │
                          ┌───▼────┐  any node error routes here:
                          │ END /  │  state.error set, graph ends gracefully (no crash)
                          │ error  │
                          └────────┘
```

## Error routing (conditional edge)

```
 node ok?  ── yes ─▶ next node
           └─ no  ─▶ error_sink (record state.error) ─▶ END
```

## Prompt

```
app/pipeline/state.py — TypedDict PipelineState: job_id, aspect_ratio, room_name,
source_image_url, upscale_factor, do_expand, duration_seconds, prompt, target_w, target_h,
upscaled_url, expanded_url, video_url, error, token_usage(dict).

app/pipeline/tools.py — LangChain @tool wrappers (upscale_tool, outpaint_tool, i2v_tool) over
app.providers.fal_client; take/return plain dicts; decorate with obs @span so each is traced.

app/pipeline/graph.py — build_graph() returns a compiled StateGraph:
  nodes: upscale_node -> expand_node (conditional on do_expand; outpaint to RATIO_DIMS) ->
         video_node (i2v on expanded_url or upscaled_url with cinematic prompt + aspect_ratio +
         duration). Conditional edge routes any node error to an error_sink -> END.
  Configure LangSmith from settings (LANGCHAIN_TRACING_V2 / project / api key); run name
  "media_pipeline.{job_id}.{aspect_ratio}".
  async run_pipeline(state) -> state: invoke compiled graph, aggregate token_usage via a
  LangChain callback handler.
Embed the StateGraph ASCII (above) as a comment at the top of graph.py.
```

## Verify
`python -c "from app.pipeline.graph import build_graph; build_graph()"` compiles; a mocked-tool dry run walks upscale→expand→video and, on a forced tool error, ends gracefully with `state.error` set.

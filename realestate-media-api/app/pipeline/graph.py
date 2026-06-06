"""Per-aspect-ratio LangGraph pipeline.

PipelineState{job_id, aspect_ratio, room_name, source_image_url, ...}
                      |
                  +---v----+  upscale_tool -> fal.clarity
                  |upscale |  sets upscaled_url
                  +---+----+
          do_expand?  |
      +---- yes ------+----- no -----+
      v               |              | (passthrough: expanded_url = upscaled_url)
  +--------+          |              |
  | expand | outpaint_tool -> fal.flux-2 (to RATIO_DIMS[w,h])
  +---+----+          |              |
      +---------------+<-------------+
                  +---v----+  i2v_tool -> fal.seedance-2
                  |  i2v   |  cinematic prompt + ratio + duration
                  +---+----+  sets video_url
                      |
                  +---v----+  any node error routes here:
                  | END /  |  state.error set, graph ends gracefully (no crash)
                  | error  |
                  +--------+
"""

from __future__ import annotations

import os

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.obs.logging import get_logger
from app.obs.spans import set_job_context
from app.pipeline.state import PipelineState
from app.pipeline.tools import i2v_tool, outpaint_tool, upscale_tool

_logger = get_logger("app.pipeline")


class TokenUsageCollector(BaseCallbackHandler):
    """Aggregate token usage across any LLM runs in the graph (fal stages add none)."""

    def __init__(self) -> None:
        self.usage: dict[str, int] = {}

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ANN001
        try:
            token_usage = (response.llm_output or {}).get("token_usage") or {}
            for key, value in token_usage.items():
                if isinstance(value, (int, float)):
                    self.usage[key] = self.usage.get(key, 0) + int(value)
        except Exception:  # pragma: no cover - defensive: never break the pipeline
            pass


def configure_langsmith() -> None:
    """Wire LangSmith tracing from settings (no-op without an API key)."""
    settings = get_settings()
    if settings.langsmith_api_key and settings.langchain_tracing_v2:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)
    else:
        # Avoid accidental tracing attempts (network) when unconfigured.
        os.environ["LANGCHAIN_TRACING_V2"] = "false"


# ── Nodes ────────────────────────────────────────────────────────────────────
async def upscale_node(state: PipelineState) -> dict:
    set_job_context(state.get("job_id", ""), state.get("aspect_ratio"))
    try:
        out = await upscale_tool.ainvoke(
            {
                "image_url": state["source_image_url"],
                "upscale_factor": state.get("upscale_factor", 2),
            }
        )
        return {"upscaled_url": out["upscaled_url"]}
    except Exception as exc:
        _logger.warning("pipeline.upscale_failed", extra={"error": repr(exc)})
        return {"error": f"upscale failed: {exc}"}


async def expand_node(state: PipelineState) -> dict:
    set_job_context(state.get("job_id", ""), state.get("aspect_ratio"))
    try:
        out = await outpaint_tool.ainvoke(
            {
                "image_url": state["upscaled_url"],
                "target_w": state["target_w"],
                "target_h": state["target_h"],
            }
        )
        return {"expanded_url": out["expanded_url"]}
    except Exception as exc:
        _logger.warning("pipeline.expand_failed", extra={"error": repr(exc)})
        return {"error": f"expand failed: {exc}"}


async def video_node(state: PipelineState) -> dict:
    set_job_context(state.get("job_id", ""), state.get("aspect_ratio"))
    # Passthrough: use the expanded image if present, else the upscaled image.
    source = state.get("expanded_url") or state.get("upscaled_url")
    try:
        out = await i2v_tool.ainvoke(
            {
                "image_url": source,
                "prompt": state["prompt"],
                "duration_seconds": state.get("duration_seconds", 5),
                "aspect_ratio": state["aspect_ratio"],
            }
        )
        return {"video_url": out["video_url"]}
    except Exception as exc:
        _logger.warning("pipeline.i2v_failed", extra={"error": repr(exc)})
        return {"error": f"i2v failed: {exc}"}


async def error_sink_node(state: PipelineState) -> dict:
    # state.error is already set; this node exists so the graph ends gracefully.
    _logger.error("pipeline.error_sink", extra={"error": state.get("error")})
    return {}


# ── Edge routing ────────────────────────────────────────────────────────────────
def _route_after_upscale(state: PipelineState) -> str:
    if state.get("error"):
        return "error_sink"
    return "expand" if state.get("do_expand") else "video"


def _route_after_expand(state: PipelineState) -> str:
    return "error_sink" if state.get("error") else "video"


def _route_after_video(state: PipelineState) -> str:
    return "error_sink" if state.get("error") else "end"


def build_graph():
    """Build and compile the per-ratio StateGraph."""
    graph = StateGraph(PipelineState)
    graph.add_node("upscale", upscale_node)
    graph.add_node("expand", expand_node)
    graph.add_node("video", video_node)
    graph.add_node("error_sink", error_sink_node)

    graph.add_edge(START, "upscale")
    graph.add_conditional_edges(
        "upscale",
        _route_after_upscale,
        {"expand": "expand", "video": "video", "error_sink": "error_sink"},
    )
    graph.add_conditional_edges(
        "expand", _route_after_expand, {"video": "video", "error_sink": "error_sink"}
    )
    graph.add_conditional_edges(
        "video", _route_after_video, {"end": END, "error_sink": "error_sink"}
    )
    graph.add_edge("error_sink", END)
    return graph.compile()


_compiled = None


def _get_compiled():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


async def run_pipeline(state: PipelineState) -> PipelineState:
    """Run the compiled graph for one ratio; aggregate token usage; return state."""
    configure_langsmith()
    compiled = _get_compiled()
    collector = TokenUsageCollector()
    run_name = f"media_pipeline.{state.get('job_id')}.{state.get('aspect_ratio')}"
    result: PipelineState = await compiled.ainvoke(
        state, config={"callbacks": [collector], "run_name": run_name}
    )
    result["token_usage"] = collector.usage
    return result

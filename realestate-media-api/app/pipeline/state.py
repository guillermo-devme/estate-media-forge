"""Pipeline state for one aspect ratio.

A plain ``TypedDict`` (total=False) so nodes can return partial updates that
LangGraph merges into the running state.
"""

from __future__ import annotations

from typing import TypedDict


class PipelineState(TypedDict, total=False):
    """State threaded through the per-ratio StateGraph."""

    # Inputs
    job_id: str
    aspect_ratio: str
    room_name: str
    source_image_url: str
    upscale_factor: int
    do_expand: bool
    duration_seconds: int
    prompt: str
    target_w: int
    target_h: int

    # Outputs (filled as nodes run)
    upscaled_url: str
    expanded_url: str
    video_url: str

    # Error routing + observability
    error: str
    token_usage: dict

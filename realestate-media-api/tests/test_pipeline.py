"""LangGraph pipeline: compiles, walks upscale->expand->video, errors end gracefully."""

from __future__ import annotations

import pytest

import app.providers.fal_client as fal
from app.pipeline.graph import build_graph, run_pipeline


@pytest.fixture
def mock_fal(monkeypatch):
    calls: dict[str, list] = {"upscale": [], "outpaint": [], "i2v": []}

    async def fake_upscale(image_url, factor):
        calls["upscale"].append((image_url, factor))
        return {"image": {"url": "https://cdn.fal/up.png"}}

    async def fake_outpaint(image_url, target_w, target_h):
        calls["outpaint"].append((image_url, target_w, target_h))
        return {"image": {"url": "https://cdn.fal/exp.png"}}

    async def fake_i2v(image_url, prompt, duration_seconds, aspect_ratio):
        calls["i2v"].append((image_url, prompt, duration_seconds, aspect_ratio))
        return {"video": {"url": "https://cdn.fal/clip.mp4"}}

    monkeypatch.setattr(fal, "run_upscale", fake_upscale)
    monkeypatch.setattr(fal, "run_outpaint", fake_outpaint)
    monkeypatch.setattr(fal, "run_image_to_video", fake_i2v)
    return calls


def _state(**overrides) -> dict:
    base = {
        "job_id": "job1",
        "aspect_ratio": "9:16",
        "room_name": "den",
        "source_image_url": "https://example.com/a.jpg",
        "upscale_factor": 2,
        "do_expand": True,
        "duration_seconds": 5,
        "prompt": "a cinematic walkthrough",
        "target_w": 1080,
        "target_h": 1920,
    }
    base.update(overrides)
    return base


def test_build_graph_compiles():
    assert build_graph() is not None


async def test_full_walk_upscale_expand_video(mock_fal):
    result = await run_pipeline(_state())
    assert result["upscaled_url"] == "https://cdn.fal/up.png"
    assert result["expanded_url"] == "https://cdn.fal/exp.png"
    assert result["video_url"] == "https://cdn.fal/clip.mp4"
    assert not result.get("error")
    assert result["token_usage"] == {}
    # i2v consumed the expanded image.
    assert mock_fal["i2v"][0][0] == "https://cdn.fal/exp.png"


async def test_no_expand_passes_upscaled_to_video(mock_fal):
    result = await run_pipeline(_state(do_expand=False))
    assert result["upscaled_url"] == "https://cdn.fal/up.png"
    assert "expanded_url" not in result
    assert result["video_url"] == "https://cdn.fal/clip.mp4"
    assert mock_fal["outpaint"] == []  # expand node skipped
    assert mock_fal["i2v"][0][0] == "https://cdn.fal/up.png"


async def test_tool_error_ends_gracefully_with_error_set(monkeypatch):
    async def boom_upscale(image_url, factor):
        raise RuntimeError("fal exploded")

    monkeypatch.setattr(fal, "run_upscale", boom_upscale)

    result = await run_pipeline(_state())
    assert "upscale failed" in result["error"]
    assert "upscaled_url" not in result
    assert "video_url" not in result  # routed to error_sink -> END, no crash


async def test_expand_error_routes_to_error_sink(monkeypatch):
    async def ok_upscale(image_url, factor):
        return {"image": {"url": "https://cdn.fal/up.png"}}

    async def boom_outpaint(image_url, target_w, target_h):
        raise RuntimeError("outpaint down")

    monkeypatch.setattr(fal, "run_upscale", ok_upscale)
    monkeypatch.setattr(fal, "run_outpaint", boom_outpaint)

    result = await run_pipeline(_state())
    assert result["upscaled_url"] == "https://cdn.fal/up.png"
    assert "expand failed" in result["error"]
    assert "video_url" not in result

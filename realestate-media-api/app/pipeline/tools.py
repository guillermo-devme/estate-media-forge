"""LangChain tool wrappers over the fal client.

Wrapping fal calls as LangChain tools lets LangSmith capture timing (and any
token/cost) per stage; each is additionally traced with the obs ``@span``
decorator. Tools take/return plain dicts.
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.obs.spans import span
from app.providers import fal_client


def _extract_image_url(result: dict) -> str:
    """Pull the output image URL from a fal result payload.

    TODO(fal-output): confirm the exact output shape on the model pages
    (clarity-upscaler / flux-2-pro outpaint) before production.
    """
    image = result.get("image")
    if isinstance(image, dict) and image.get("url"):
        return image["url"]
    images = result.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        url = images[0].get("url")
        if url:
            return url
    raise ValueError(f"no image url in fal result (keys={list(result)})")


def _extract_video_url(result: dict) -> str:
    """Pull the output video URL from a fal result payload.

    TODO(fal-output): confirm Seedance 2.0 output shape before production.
    """
    video = result.get("video")
    if isinstance(video, dict) and video.get("url"):
        return video["url"]
    if isinstance(result.get("video_url"), str):
        return result["video_url"]
    raise ValueError(f"no video url in fal result (keys={list(result)})")


@tool
@span("tool.upscale")
async def upscale_tool(image_url: str, upscale_factor: int = 2) -> dict:
    """Upscale an image with fal. Returns {'upscaled_url': str}."""
    result = await fal_client.run_upscale(image_url, upscale_factor)
    return {"upscaled_url": _extract_image_url(result)}


@tool
@span("tool.outpaint")
async def outpaint_tool(image_url: str, target_w: int, target_h: int) -> dict:
    """Expand/outpaint an image to a target canvas. Returns {'expanded_url': str}."""
    result = await fal_client.run_outpaint(image_url, target_w, target_h)
    return {"expanded_url": _extract_image_url(result)}


@tool
@span("tool.i2v")
async def i2v_tool(image_url: str, prompt: str, duration_seconds: int, aspect_ratio: str) -> dict:
    """Generate a cinematic clip from an image. Returns {'video_url': str}."""
    result = await fal_client.run_image_to_video(image_url, prompt, duration_seconds, aspect_ratio)
    return {"video_url": _extract_video_url(result)}

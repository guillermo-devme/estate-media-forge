"""Canonical string enums shared across schemas, pricing, pipeline, and jobs.

These are the single source of truth for the vocabulary of the system. ``pricing``
(03) imports ``FalStage``/``ServiceType`` from here rather than redefining them.
"""

from __future__ import annotations

from enum import Enum


class AspectRatio(str, Enum):
    """Supported media-kit aspect ratios."""

    R1_1 = "1:1"
    R9_16 = "9:16"
    R16_9 = "16:9"


class ServiceType(str, Enum):
    """A user-facing priced service."""

    UPSCALE = "upscale"
    MEDIA_KIT = "media_kit"
    IMAGE_TO_VIDEO = "image_to_video"


class JobStatus(str, Enum):
    """Lifecycle status of a job (and of an individual aspect-ratio sub-job)."""

    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


class FalStage(str, Enum):
    """A single fal.ai pipeline stage (also the COST_TABLE / MODEL_REGISTRY key)."""

    UPSCALE = "upscale"
    OUTPAINT = "outpaint"
    I2V = "i2v"


# Default fan-out: all three aspect ratios.
ALL_ASPECT_RATIOS: tuple[AspectRatio, ...] = (
    AspectRatio.R1_1,
    AspectRatio.R9_16,
    AspectRatio.R16_9,
)

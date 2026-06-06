"""Response contracts (Pydantic v2).

Every value is expressed in **credits**. No response carries USD/price, internal
cost, or an authoritative balance — balance lives in Wix.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.enums import AspectRatio, FalStage, JobStatus, ServiceType


class QuoteBreakdownItem(BaseModel):
    """One stage line of a quote. Credits only — never a USD field."""

    stage: FalStage = Field(..., description="Pipeline stage.")
    quantity: float = Field(..., description="Units priced (images or seconds).")
    credits: int = Field(..., ge=0, description="Credits attributed to this stage.")

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"stage": "i2v", "quantity": 5, "credits": 1088}]}
    )


class QuotationResponse(BaseModel):
    """Credits quote for a service, with a per-stage breakdown. No USD/balance."""

    service: ServiceType = Field(..., description="Service that was priced.")
    total_credits: int = Field(..., ge=0, description="Total credits (sum of per-ratio units).")
    breakdown: list[QuoteBreakdownItem] = Field(
        default_factory=list, description="Per-stage credit breakdown."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "service": "media_kit",
                    "total_credits": 3366,
                    "breakdown": [
                        {"stage": "upscale", "quantity": 3, "credits": 60},
                        {"stage": "outpaint", "quantity": 3, "credits": 44},
                        {"stage": "i2v", "quantity": 15, "credits": 3262},
                    ],
                }
            ]
        }
    )


class AllowanceResponse(BaseModel):
    """How many of each service a balance buys (counts only)."""

    allowance: dict[str, int] = Field(
        ..., description="Service description -> how many the balance buys."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"allowance": {"upscale_images": 500, "videos_8s": 5, "media_kits": 2}}]
        }
    )


class AssetSet(BaseModel):
    """Generated assets for a single aspect ratio."""

    aspect_ratio: AspectRatio = Field(..., description="Aspect ratio of this asset set.")
    upscaled_url: HttpUrl | None = Field(default=None, description="Upscaled image URL.")
    expanded_url: HttpUrl | None = Field(default=None, description="Expanded/outpainted image URL.")
    video_url: HttpUrl | None = Field(default=None, description="Cinematic video URL.")
    status: JobStatus = Field(..., description="Status of this aspect-ratio sub-job.")
    error: str | None = Field(default=None, description="Error detail if this ratio failed.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "aspect_ratio": "16:9",
                    "upscaled_url": "http://localhost:8000/media/job123/16x9_upscaled.png",
                    "expanded_url": "http://localhost:8000/media/job123/16x9_expanded.png",
                    "video_url": "http://localhost:8000/media/job123/16x9.mp4",
                    "status": "completed",
                    "error": None,
                }
            ]
        }
    )


class JobAccepted(BaseModel):
    """202 response after a submit: where to poll and what was charged."""

    job_id: str = Field(..., description="Job identifier.")
    status: JobStatus = Field(..., description="Initial job status.")
    service: ServiceType = Field(..., description="Service requested.")
    poll_url: str = Field(..., description="URL to poll for job status.")
    quoted_credits: int = Field(..., ge=0, description="Credits debited by Wix for this job.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "job_abc123",
                    "status": "queued",
                    "service": "media_kit",
                    "poll_url": "/v1/jobs/job_abc123",
                    "quoted_credits": 3366,
                }
            ]
        }
    )


class JobStatusResponse(BaseModel):
    """Full job status (ownership-checked). Credits only; refunds reconcile to charge."""

    job_id: str = Field(..., description="Job identifier.")
    member_id: str = Field(..., description="Owning member id.")
    service: ServiceType = Field(..., description="Service requested.")
    status: JobStatus = Field(..., description="Aggregate job status.")
    created_at: datetime = Field(..., description="Creation timestamp.")
    updated_at: datetime = Field(..., description="Last update timestamp.")
    assets: list[AssetSet] = Field(default_factory=list, description="Per-ratio asset sets.")
    quoted_credits: int = Field(..., ge=0, description="Credits debited by Wix for this job.")
    refunded_credits: int = Field(
        default=0, ge=0, description="Credits refunded to Wix on partial/total failure."
    )
    # Token counts only (e.g. prompt/completion/total) — never USD cost.
    token_usage: dict[str, int] | None = Field(
        default=None, description="LangSmith token counts (no cost/USD)."
    )
    error: str | None = Field(default=None, description="Job-level error detail, if any.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "job_abc123",
                    "member_id": "mem_abc123",
                    "service": "media_kit",
                    "status": "partial",
                    "created_at": "2026-06-05T12:00:00Z",
                    "updated_at": "2026-06-05T12:03:00Z",
                    "assets": [
                        {
                            "aspect_ratio": "1:1",
                            "video_url": "http://localhost:8000/media/job_abc123/1x1.mp4",
                            "status": "completed",
                        },
                        {"aspect_ratio": "9:16", "status": "failed", "error": "i2v timeout"},
                    ],
                    "quoted_credits": 3366,
                    "refunded_credits": 1122,
                    "token_usage": {"total_tokens": 4096},
                }
            ]
        }
    )

"""Request contracts (Pydantic v2).

Submit requests carry ``member_id`` (the authenticated Wix member), ``client_ref``
(the Wix-side spend reference), and ``quoted_credits`` (the credits the Wix
backend already debited from the wallet). There is no hold/quote_id and no
wallet/top-up schema here — Wix owns the balance. Quotation is pure pricing.

No request or response carries USD/price; only credits.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.schemas.enums import ALL_ASPECT_RATIOS, AspectRatio, ServiceType

# Cinematic prompt template; ``{room_name}`` is filled in when no override is given.
CINEMATIC_PROMPT_TEMPLATE = (
    "Create a 3d walkthrough animation of this property room: {room_name}. Add soft, "
    "clean elegant lighting and smooth camera movements. Follow the same layout of this "
    "image precisely and maintain strict architectural consistency throughout the "
    "cinematic sequence."
)


def _default_ratios() -> list[AspectRatio]:
    return list(ALL_ASPECT_RATIOS)


class SignedActor(BaseModel):
    """Mixin: the authenticated member a request acts on behalf of."""

    member_id: str = Field(
        ...,
        min_length=1,
        description="Authenticated Wix member id this request acts on behalf of.",
    )


class _SubmitActor(SignedActor):
    """Submit requests also carry the Wix spend reference and quoted credits."""

    client_ref: str = Field(
        ...,
        min_length=1,
        description="Wix-side spend reference (idempotency key for the debit).",
    )
    quoted_credits: int = Field(
        ...,
        ge=0,
        description="Credits the Wix backend already debited for this submission.",
    )


class UpscaleRequest(_SubmitActor):
    """Standalone upscale of an image across one or more aspect ratios."""

    image_url: HttpUrl = Field(..., description="Source image URL (untrusted; validated upstream).")
    aspect_ratios: list[AspectRatio] = Field(
        default_factory=_default_ratios, description="Aspect ratios to produce."
    )
    upscale_factor: int = Field(default=2, ge=2, le=4, description="Upscale multiplier (2–4).")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "member_id": "mem_abc123",
                    "client_ref": "spend_001",
                    "quoted_credits": 60,
                    "image_url": "https://example.com/listing/front.jpg",
                    "aspect_ratios": ["1:1", "9:16", "16:9"],
                    "upscale_factor": 2,
                }
            ]
        }
    )

    @field_validator("aspect_ratios")
    @classmethod
    def _ratios_not_empty(cls, value: list[AspectRatio]) -> list[AspectRatio]:
        if not value:
            raise ValueError("aspect_ratios must not be empty")
        return value


class ImageToVideoRequest(_SubmitActor):
    """Cinematic image-to-video for one or more aspect ratios."""

    image_url: HttpUrl = Field(..., description="Source image URL (untrusted; validated upstream).")
    room_name: str = Field(..., min_length=1, description="Room/space name for the prompt.")
    aspect_ratios: list[AspectRatio] = Field(
        default_factory=_default_ratios, description="Aspect ratios to produce."
    )
    duration_seconds: int = Field(default=5, ge=3, le=10, description="Clip duration (3–10s).")
    prompt_override: str | None = Field(
        default=None, description="Optional prompt replacing the cinematic default."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "member_id": "mem_abc123",
                    "client_ref": "spend_002",
                    "quoted_credits": 1741,
                    "image_url": "https://example.com/listing/living.jpg",
                    "room_name": "living room",
                    "aspect_ratios": ["16:9"],
                    "duration_seconds": 8,
                }
            ]
        }
    )

    @property
    def effective_prompt(self) -> str:
        """The prompt to send to the i2v model (override or cinematic default)."""
        if self.prompt_override:
            return self.prompt_override
        return CINEMATIC_PROMPT_TEMPLATE.format(room_name=self.room_name)


class MediaKitRequest(_SubmitActor):
    """Full media kit: upscale → optional expand/outpaint → image-to-video, ×3 ratios."""

    image_url: HttpUrl = Field(..., description="Source image URL (untrusted; validated upstream).")
    room_name: str = Field(..., min_length=1, description="Room/space name for the prompt.")
    aspect_ratios: list[AspectRatio] = Field(
        default_factory=_default_ratios, description="Aspect ratios to produce."
    )
    do_expand: bool = Field(default=True, description="Run the expand/outpaint stage.")
    upscale_factor: int = Field(default=2, ge=2, le=4, description="Upscale multiplier (2–4).")
    duration_seconds: int = Field(default=5, ge=3, le=10, description="Clip duration (3–10s).")
    prompt_override: str | None = Field(
        default=None, description="Optional prompt replacing the cinematic default."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "member_id": "mem_abc123",
                    "client_ref": "spend_003",
                    "quoted_credits": 3366,
                    "image_url": "https://example.com/listing/kitchen.jpg",
                    "room_name": "kitchen",
                    "aspect_ratios": ["1:1", "9:16", "16:9"],
                    "do_expand": True,
                    "upscale_factor": 2,
                    "duration_seconds": 5,
                }
            ]
        }
    )

    @property
    def effective_prompt(self) -> str:
        """The prompt to send to the i2v model (override or cinematic default)."""
        if self.prompt_override:
            return self.prompt_override
        return CINEMATIC_PROMPT_TEMPLATE.format(room_name=self.room_name)


class QuotationRequest(SignedActor):
    """Pure pricing request — a credits quote for a service. No wallet side effects."""

    service: ServiceType = Field(..., description="Service to price.")
    image_url: HttpUrl | None = Field(
        default=None, description="Optional source image (not required to price)."
    )
    room_name: str | None = Field(default=None, description="Optional room name.")
    aspect_ratios: list[AspectRatio] = Field(
        default_factory=_default_ratios, description="Aspect ratios to price."
    )
    duration_seconds: int = Field(default=5, ge=3, le=10, description="Clip duration (3–10s).")
    do_expand: bool = Field(default=True, description="Whether the expand stage is included.")
    upscale_factor: int = Field(default=2, ge=2, le=4, description="Upscale multiplier (2–4).")
    images: int = Field(default=1, ge=1, description="Image count for ratio-less upscale pricing.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "member_id": "mem_abc123",
                    "service": "media_kit",
                    "aspect_ratios": ["1:1", "9:16", "16:9"],
                    "duration_seconds": 5,
                    "do_expand": True,
                    "upscale_factor": 2,
                }
            ]
        }
    )

    @model_validator(mode="after")
    def _validate_per_service(self) -> QuotationRequest:
        if self.service in (ServiceType.IMAGE_TO_VIDEO, ServiceType.MEDIA_KIT):
            if not self.aspect_ratios:
                raise ValueError("aspect_ratios must not be empty for this service")
        return self


class AllowanceRequest(SignedActor):
    """Compute how many of each service a Wix-provided credit balance buys."""

    balance: int = Field(
        ..., ge=0, description="Credit balance (passed in by Wix; the authority is Wix CMS)."
    )

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"member_id": "mem_abc123", "balance": 10000}]}
    )

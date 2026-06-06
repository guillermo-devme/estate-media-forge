"""Application settings and the swappable fal.ai model registry.

Settings are loaded from environment / ``.env`` via pydantic-settings and cached
with :func:`get_settings`. Secrets default to empty strings so the module imports
cleanly without a ``.env`` present; presence is enforced at request time by the
auth layer (06), not at import time.

The three fal endpoint ids below were verified against live fal.ai docs
(2026-06-05) and are each independently overridable via env so models can be
swapped without code changes:

* upscale  -> ``fal-ai/clarity-upscaler``          (FAL_MODEL_UPSCALE)
* outpaint -> ``fal-ai/flux-2-pro/outpaint``        (FAL_MODEL_OUTPAINT)
* i2v      -> ``bytedance/seedance-2.0/image-to-video`` (FAL_MODEL_I2V)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fixed media-kit aspect ratios → (width, height) in pixels.
RATIO_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Service auth (Wix → API trust + refund callback) ──────────────────────
    # Empty defaults so the module imports without a .env; auth (06) enforces
    # presence at request time.
    service_key: str = Field(default="", validation_alias="FASTAPI_SERVICE_KEY")
    service_hmac_secret: str = Field(default="", validation_alias="SERVICE_HMAC_SECRET")
    wix_refund_url: str = Field(default="", validation_alias="WIX_REFUND_URL")

    # ── fal.ai ────────────────────────────────────────────────────────────────
    fal_key: str = Field(default="", validation_alias="FAL_KEY")

    # ── Infrastructure ─────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379", validation_alias="REDIS_URL")
    ledger_dsn: str = Field(default="sqlite+aiosqlite:///./usage.db", validation_alias="LEDGER_DSN")
    media_dir: str = Field(default="media", validation_alias="MEDIA_DIR")
    public_base_url: str = Field(
        default="http://localhost:8000", validation_alias="PUBLIC_BASE_URL"
    )

    # ── Concurrency / backpressure ──────────────────────────────────────────────
    max_fal_concurrency: int = Field(default=8, validation_alias="MAX_FAL_CONCURRENCY")
    max_queue_depth: int = Field(default=500, validation_alias="MAX_QUEUE_DEPTH")

    # ── Token economy (USD stays server-side; clients only see credits) ─────────
    earnings_ratio: float = Field(default=3.2, validation_alias="EARNINGS_RATIO")
    credit_peg_usd: float = Field(default=0.01, validation_alias="CREDIT_PEG_USD")

    # Hold lifetime. Authoritative holds live in Wix CMS (prompt 09 superseded);
    # kept here for parity with the config diagram / any local reconciliation use.
    hold_ttl_seconds: int = Field(default=900, validation_alias="HOLD_TTL_SECONDS")

    # Optional JSON overriding the provider cost table (see app/pricing.py), e.g.
    # '{"upscale": 0.06, "outpaint": 0.045, "i2v": 0.68}'. Lets ops correct fal
    # costs without a code change. USD stays server-side.
    pricing_json: str | None = Field(default=None, validation_alias="PRICING_JSON")

    # ── Observability ────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    langsmith_api_key: str | None = Field(default=None, validation_alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="realestate-media", validation_alias="LANGSMITH_PROJECT")
    langchain_tracing_v2: bool = Field(default=True, validation_alias="LANGCHAIN_TRACING_V2")

    # ── Alerts & circuit breaker ─────────────────────────────────────────────────
    google_chat_webhook_url: str = Field(default="", validation_alias="GOOGLE_CHAT_WEBHOOK_URL")
    fal_balance_alert_threshold_usd: float = Field(
        default=20.0, validation_alias="FAL_BALANCE_ALERT_THRESHOLD_USD"
    )
    fal_balance_check_interval_seconds: int = Field(
        default=300, validation_alias="FAL_BALANCE_CHECK_INTERVAL_SECONDS"
    )

    # ── Swappable model registry (each env-overridable) ──────────────────────────
    # Verified against fal.ai docs on 2026-06-05.
    fal_model_upscale: str = Field(
        default="fal-ai/clarity-upscaler", validation_alias="FAL_MODEL_UPSCALE"
    )
    fal_model_outpaint: str = Field(
        default="fal-ai/flux-2-pro/outpaint", validation_alias="FAL_MODEL_OUTPAINT"
    )
    # NOTE: Seedance 2.0 i2v endpoint id has NO "fal-ai/" prefix (unlike the older
    # seedance/v1 variants). Confirmed on fal docs + model page. The 01/INDEX
    # placeholder "fal-ai/bytedance/seedance-2.0/..." was incorrect.
    fal_model_i2v: str = Field(
        default="bytedance/seedance-2.0/image-to-video", validation_alias="FAL_MODEL_I2V"
    )

    @property
    def MODEL_REGISTRY(self) -> dict[str, str]:  # noqa: N802 (intentional public name)
        """Stage → fal endpoint id mapping (built from the env-overridable fields)."""
        return {
            "upscale": self.fal_model_upscale,
            "outpaint": self.fal_model_outpaint,
            "i2v": self.fal_model_i2v,
        }

    @property
    def RATIO_DIMS(self) -> dict[str, tuple[int, int]]:  # noqa: N802 (intentional public name)
        """Aspect ratio → (width, height) pixel dimensions."""
        return dict(RATIO_DIMS)


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()

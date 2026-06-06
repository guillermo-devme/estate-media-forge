"""FastAPI application factory.

Placeholder root only — routers, middleware, and lifecycle wiring are added in
later prompts (13+). This module must import cleanly so `uvicorn app.main:app`
boots without errors at every step of the build.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="Real-Estate Media-Kit API",
    version="0.1.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    """Placeholder root route (replaced by health/router wiring in later prompts)."""
    return {"service": "realestate-media-api", "status": "ok"}

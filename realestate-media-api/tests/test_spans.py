"""Nested span logging produces correctly nested JSON with elapsed_ms."""

from __future__ import annotations

import io
import json
import logging

import pytest

from app.obs.logging import build_formatter
from app.obs.spans import set_job_context, span, span_ctx


@pytest.fixture
def captured_logs():
    """Attach a JSON handler to the span logger and yield parsed records."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(build_formatter())

    logger = logging.getLogger("app.span")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    previous_propagate = logger.propagate
    logger.propagate = False
    try:
        yield buffer
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous_propagate


@span("inner")
async def _inner() -> int:
    return 42


@span("outer")
async def _outer() -> int:
    return await _inner()


def _records(buffer: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


async def test_nested_spans_nest_and_time(captured_logs):
    set_job_context("job1", "9:16")
    result = await _outer()
    assert result == 42

    records = _records(captured_logs)
    by_event = {(r["message"], r["span"]): r for r in records}

    # Both spans start and end.
    assert ("span.start", "outer") in by_event
    assert ("span.start", "outer.inner") in by_event
    assert ("span.end", "outer") in by_event
    assert ("span.end", "outer.inner") in by_event

    outer_end = by_event[("span.end", "outer")]
    inner_end = by_event[("span.end", "outer.inner")]

    # Nesting: inner's parent is outer; depths increment.
    assert outer_end["parent_span"] is None
    assert outer_end["depth"] == 0
    assert inner_end["parent_span"] == "outer"
    assert inner_end["depth"] == 1

    # Context propagated to every record.
    assert all(r["job_id"] == "job1" and r["ratio"] == "9:16" for r in records)

    # elapsed_ms present on close (and not on start).
    assert "elapsed_ms" in outer_end and isinstance(outer_end["elapsed_ms"], (int, float))
    assert "elapsed_ms" in inner_end
    assert "elapsed_ms" not in by_event[("span.start", "outer")]

    # GCloud severity + RFC3339 timestamp present.
    assert outer_end["severity"] == "INFO"
    assert "T" in outer_end["timestamp"]


async def test_span_error_logs_and_reraises(captured_logs):
    set_job_context("job2", None)

    @span("boom")
    async def _boom() -> None:
        raise ValueError("kaboom")

    with pytest.raises(ValueError, match="kaboom"):
        await _boom()

    records = _records(captured_logs)
    errors = [r for r in records if r["message"] == "span.error"]
    assert len(errors) == 1
    assert errors[0]["span"] == "boom"
    assert "elapsed_ms" in errors[0]
    assert errors[0]["severity"] == "ERROR"


async def test_span_ctx_inline_block(captured_logs):
    set_job_context("job3", "1:1")
    async with span_ctx("media_kit"):
        async with span_ctx("ratio_9:16"):
            async with span_ctx("i2v"):
                pass

    records = _records(captured_logs)
    spans = {r["span"] for r in records}
    assert "media_kit.ratio_9:16.i2v" in spans
    deepest = next(r for r in records if r["span"] == "media_kit.ratio_9:16.i2v")
    assert deepest["parent_span"] == "media_kit.ratio_9:16"
    assert deepest["depth"] == 2

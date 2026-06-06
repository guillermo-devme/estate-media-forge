"""Nestable async span/timer instrumentation.

A span stack is held in a contextvar so spans nest across ``await`` boundaries
within a task. Each span emits ``span.start`` on enter and ``span.end`` (or
``span.error``) on close with ``elapsed_ms``. Every record carries ``job_id``,
``ratio``, ``span`` (dotted path, e.g. ``media_kit.ratio_9:16.i2v``),
``parent_span``, and ``depth``.
"""

from __future__ import annotations

import functools
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from app.obs.logging import get_logger, job_id_var, ratio_var

# Stack of active span names for the current context.
span_stack_var: ContextVar[tuple[str, ...]] = ContextVar("span_stack", default=())

_logger = get_logger("app.span")

T = TypeVar("T")


def set_job_context(job_id: str, ratio: str | None = None) -> None:
    """Bind ``job_id``/``ratio`` into the logging context for subsequent records."""
    job_id_var.set(job_id)
    ratio_var.set(ratio)


def _base_fields(path: str, parent: str | None, depth: int) -> dict[str, Any]:
    return {
        "job_id": job_id_var.get(),
        "ratio": ratio_var.get(),
        "span": path,
        "parent_span": parent,
        "depth": depth,
    }


@asynccontextmanager
async def span_ctx(name: str) -> AsyncIterator[None]:
    """Async context manager timing an inline block as a nested span."""
    stack = span_stack_var.get()
    new_stack = (*stack, name)
    token = span_stack_var.set(new_stack)

    path = ".".join(new_stack)
    parent = ".".join(new_stack[:-1]) or None
    depth = len(new_stack) - 1
    base = _base_fields(path, parent, depth)

    start = time.perf_counter()
    _logger.info("span.start", extra=base)
    try:
        yield
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        _logger.error("span.error", extra={**base, "elapsed_ms": elapsed_ms, "error": repr(exc)})
        raise
    else:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        _logger.info("span.end", extra={**base, "elapsed_ms": elapsed_ms})
    finally:
        span_stack_var.reset(token)


def span(name: str) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator timing an async function as a nested span."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async with span_ctx(name):
                return await func(*args, **kwargs)

        return wrapper

    return decorator

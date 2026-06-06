"""Structured JSON logging compatible with Google Cloud Logging.

Emits one JSON object per record with a GCloud ``severity``, an RFC3339
``timestamp``, the ``message``, and any extras. Request/job context (``job_id``,
``ratio``) is carried in contextvars and injected into every record by
:class:`ContextFilter`, so logs correlate across the async pipeline.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

try:  # python-json-logger >= 3 (modern path)
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # pragma: no cover - older fallback
    from pythonjsonlogger.jsonlogger import JsonFormatter

# ── Logging context (set via app.obs.spans.set_job_context) ────────────────────
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)
ratio_var: ContextVar[str | None] = ContextVar("ratio", default=None)

# Python level name -> Google Cloud Logging severity.
_SEVERITY_MAP: dict[str, str] = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


class GCloudJsonFormatter(JsonFormatter):
    """JSON formatter that adds GCloud ``severity`` and an RFC3339 ``timestamp``."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["severity"] = _SEVERITY_MAP.get(record.levelname, record.levelname)
        log_record["timestamp"] = datetime.fromtimestamp(
            record.created, tz=timezone.utc
        ).isoformat()
        if not log_record.get("message"):
            log_record["message"] = record.getMessage()


class ContextFilter(logging.Filter):
    """Inject the current job_id/ratio into every record (if not already set)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "job_id"):
            record.job_id = job_id_var.get()
        if not hasattr(record, "ratio"):
            record.ratio = ratio_var.get()
        return True


def build_formatter() -> GCloudJsonFormatter:
    """Return the standard JSON formatter (also used by tests)."""
    # rename_fields keeps a stable key for the log message under "message".
    return GCloudJsonFormatter("%(message)s")


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging to emit GCloud-compatible JSON to stdout.

    Idempotent: replaces any handler previously installed by this function.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Drop handlers we previously installed so re-configuring doesn't duplicate.
    for handler in list(root.handlers):
        if getattr(handler, "_realestate_json", False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(build_formatter())
    handler.addFilter(ContextFilter())
    handler._realestate_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger."""
    return logging.getLogger(name)

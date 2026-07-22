"""Structured stderr logging for REAPER MCP."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_STRUCTURED_FIELDS = (
    "request_id",
    "command",
    "duration_ms",
    "result",
    "error_code",
    "target_ids",
)


class JsonLogFormatter(logging.Formatter):
    """Format application log records as one compact JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Return a stable JSON representation of a log record."""

        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", record.getMessage()),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Configure REAPER MCP logs on stderr without touching the root logger."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())

    logger = logging.getLogger("reaper_mcp")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

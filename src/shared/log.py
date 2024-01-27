"""Structured logging: one JSON object per line on stdout.

CloudWatch Logs Insights can filter and aggregate on the fields directly,
for example ``filter level = "ERROR" | stats count() by function_name``.

Usage in a handler module::

    logger = logging.getLogger(__name__)
    logger.info("item created", extra={"item_id": item.id})

Keys passed in ``extra`` become top-level fields. Do not log request bodies,
tokens or anything else you would not want to read in a log viewer.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
_context: dict = {}


def set_context(**fields) -> None:
    """Fields added to every log line until :func:`clear_context` (request id, function name)."""
    _context.update({key: value for key, value in fields.items() if value is not None})


def clear_context() -> None:
    _context.clear()


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": self.service,
            "logger": record.name,
        }
        payload.update(_context)
        payload.update({key: value for key, value in vars(record).items() if key not in _STANDARD_ATTRS})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure(service: str, level: str = "INFO", stream=None) -> None:
    """Install the JSON handler on the root logger. Safe to call on every invocation.

    Inside Lambda the runtime has already attached its own plain-text handler
    to the root logger; it is removed so each line is logged once, as JSON.
    """
    root = logging.getLogger()
    in_lambda = "AWS_LAMBDA_FUNCTION_NAME" in os.environ
    for handler in list(root.handlers):
        if getattr(handler, "_starter_json", False) or in_lambda:
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    handler._starter_json = True
    root.addHandler(handler)
    root.setLevel(level)
    # botocore logs every request at DEBUG, including headers; keep it quieter than the app.
    for noisy in ("boto3", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(logging.getLevelName(level), logging.WARNING))

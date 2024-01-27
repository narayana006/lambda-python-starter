"""The wrapper every handler uses: config, logging context, and error logging."""

from __future__ import annotations

import functools
import logging

from . import log
from .config import get_config

logger = logging.getLogger(__name__)
_cold_start = True


def lambda_handler(func):
    """Decorate ``func(event, context)``.

    * Loads configuration (fails fast with a clear error if it is invalid).
    * Configures JSON logging and attaches the request id, function name and
      a ``cold_start`` flag to every log line of the invocation.
    * Logs an unhandled exception with its traceback, then re-raises it so
      Lambda records the invocation as failed and its retry behaviour applies.
    """

    @functools.wraps(func)
    def wrapper(event, context):
        global _cold_start
        config = get_config()
        log.configure(config.service_name, config.log_level)
        log.set_context(
            aws_request_id=getattr(context, "aws_request_id", None),
            function_name=getattr(context, "function_name", None),
            cold_start=_cold_start,
        )
        _cold_start = False
        try:
            return func(event, context)
        except Exception:
            logger.exception("unhandled error")
            raise
        finally:
            log.clear_context()

    return wrapper

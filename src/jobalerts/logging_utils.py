"""Structured logging: every line carries a run_id, source and event."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class RunIdFilter(logging.Filter):
    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", "-"),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_run_logger(name: str, run_id: str, log_file=None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file))

    for handler in handlers:
        handler.setFormatter(JsonLineFormatter())
        handler.addFilter(RunIdFilter(run_id))
        logger.addHandler(handler)

    return logger


def log_fields(**fields) -> dict:
    """Attach structured fields to a log call: logger.info('msg', extra=log_fields(count=3))."""
    return {"fields": fields}

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        rid = request_id_var.get()
        if rid:
            log["request_id"] = rid

        if hasattr(record, "transaction_id"):
            log["transaction_id"] = record.transaction_id

        if hasattr(record, "account_id"):
            log["account_id"] = record.account_id

        if hasattr(record, "status_code"):
            log["status_code"] = record.status_code

        if hasattr(record, "method"):
            log["method"] = record.method

        if hasattr(record, "path"):
            log["path"] = record.path

        if hasattr(record, "duration_ms"):
            log["duration_ms"] = record.duration_ms

        if record.exc_info and record.exc_info[1]:
            log["error"] = str(record.exc_info[1])
            log["error_type"] = type(record.exc_info[1]).__name__

        return json.dumps(log)


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False

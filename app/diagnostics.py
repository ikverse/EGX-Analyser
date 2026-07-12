"""Safe, local diagnostics for the desktop application's API engine."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOGGER_NAME = "egx.diagnostics"


def diagnostics_directory() -> Path:
    preferred = Path(os.getenv("LOCALAPPDATA", Path.home())) / "EGX Intelligence" / "logs"
    fallback = Path(tempfile.gettempdir()) / "EGX Intelligence" / "logs"
    for candidate in (preferred, fallback):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("Unable to create a local diagnostics directory")


def diagnostics_path() -> Path:
    return diagnostics_directory() / "api-diagnostics.jsonl"


class JsonDiagnosticFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status_code", "duration_ms", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_diagnostics() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    handler = RotatingFileHandler(diagnostics_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(JsonDiagnosticFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def logger() -> logging.Logger:
    return configure_diagnostics()


def recent_entries(limit: int = 50) -> list[dict[str, Any]]:
    path = diagnostics_path()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"level": "WARNING", "event": "unreadable_diagnostic_entry"})
    return entries

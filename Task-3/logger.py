# ─────────────────────────────────────────────
# project/logger.py
#
# Application logging via the standard library ``logging`` module.
# Pipeline executions are written as NDJSON to LOG_FILE for the UI sidebar.
# General logs go to console and logs/app.log.
# ─────────────────────────────────────────────
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_FILE = Path(os.getenv("LOG_FILE", str(LOG_DIR / "query_logs.json")))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_PACKAGE = "text2sql"
_configured = False


def setup_logging() -> None:
    """Configure package loggers once (console + rotating-style app log file)."""
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, LOG_LEVEL, logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger(_PACKAGE)
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    app_log = LOG_DIR / "app.log"
    try:
        file_handler = logging.FileHandler(app_log, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning("Could not open app log %s: %s", app_log, exc)

    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the ``text2sql`` namespace."""
    setup_logging()
    if name:
        return logging.getLogger(f"{_PACKAGE}.{name}")
    return logging.getLogger(_PACKAGE)


def _execution_logger() -> logging.Logger:
    """Dedicated logger: one JSON object per line, no propagation to app.log."""
    setup_logging()
    logger = logging.getLogger(f"{_PACKAGE}.execution")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    except OSError as exc:
        logging.getLogger(_PACKAGE).warning(
            "Could not open execution log %s: %s", LOG_FILE, exc
        )
    return logger


def log_execution(output: dict[str, Any]) -> None:
    """Record one pipeline run (success or failure) for auditing and the UI."""
    record = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "question": output.get("question", ""),
        "sql": output.get("sql", ""),
        "status": output.get("status", "failed"),
        "retry_attempted": output.get("retry_attempted", False),
        "retry_succeeded": output.get("retry_succeeded", False),
        "error": output.get("error", ""),
        "row_count": len(output.get("result", [])),
    }
    _execution_logger().info(json.dumps(record, ensure_ascii=False))


def read_logs(last_n: int | None = None) -> list[dict[str, Any]]:
    """Read execution records from LOG_FILE (newest last)."""
    if not LOG_FILE.exists():
        return []

    records: list[dict[str, Any]] = []
    with LOG_FILE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if last_n is not None:
        records = records[-last_n:]
    return records

"""Executor agent: runs validated SQL safely against PostgreSQL."""

from __future__ import annotations

from typing import Any

from app.config import logger
from app.tools.db_tools import execute_read_query


def run_executor(state: dict[str, Any]) -> dict[str, Any]:
    """Execute validated SQL and store JSON-serializable results."""
    sql = state.get("generated_sql", "")
    logger.info("[Executor] Starting execution")

    result = execute_read_query(sql)

    if result.get("success"):
        logger.info("[Executor] Success | rows=%d", result.get("row_count", 0))
        return {
            "execution_results": result,
            "execution_error": None,
        }

    error_msg = result.get("error") or "Unknown execution error"
    logger.error("[Executor] Failed | error=%s", error_msg)
    errors = list(state.get("errors", []))
    errors.append(f"Execution error: {error_msg}")
    return {
        "execution_results": result,
        "execution_error": error_msg,
        "errors": errors,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def executor_decision(state: dict[str, Any]) -> str:
    """Route to summarizer or retry SQL generation on execution failure."""
    results = state.get("execution_results") or {}
    if results.get("success"):
        return "summarize"
    if state.get("retry_count", 0) >= state.get("max_retries", 3):
        return "fail"
    return "retry"

"""Validator agent: syntax and read-only safety checks."""

from __future__ import annotations

import re
from typing import Any

import sqlparse

from app.config import logger
from app.tools.db_tools import is_read_only_sql


def _syntax_check(sql: str) -> list[str]:
    """Parse SQL and collect syntax-level issues."""
    errors: list[str] = []
    if not sql or not sql.strip():
        return ["SQL query is empty."]

    try:
        parsed = sqlparse.parse(sql)
    except Exception as exc:
        return [f"SQL parse error: {exc}"]

    if not parsed:
        return ["Could not parse SQL."]

    for statement in parsed:
        stmt_type = statement.get_type()
        if stmt_type and stmt_type.upper() not in ("SELECT", "UNKNOWN"):
            errors.append(f"Disallowed statement type: {stmt_type}")

    # Block comments that might hide malicious fragments
    if re.search(r"/\*.*?\*/", sql, re.DOTALL):
        errors.append("Block comments are not allowed.")

    return errors


def run_validator(state: dict[str, Any]) -> dict[str, Any]:
    """Validate generated SQL for safety and basic syntax."""
    sql = (state.get("generated_sql") or "").strip()
    logger.info("[Validator] Starting | sql=%s", sql[:200])

    errors: list[str] = []

    ok, reason = is_read_only_sql(sql)
    if not ok and reason:
        errors.append(reason)

    errors.extend(_syntax_check(sql))

    is_valid = len(errors) == 0
    feedback = "; ".join(errors) if errors else None

    if is_valid:
        logger.info("[Validator] SQL passed validation")
    else:
        logger.warning("[Validator] SQL failed | errors=%s", feedback)

    return {
        "is_valid_sql": is_valid,
        "validation_feedback": feedback,
        "errors": list(state.get("errors", [])) + ([] if is_valid else errors),
        "retry_count": state.get("retry_count", 0) + (0 if is_valid else 1),
    }


def validator_decision(state: dict[str, Any]) -> str:
    """Routing helper: proceed to execute or retry generation."""
    if state.get("is_valid_sql"):
        return "execute"
    if state.get("retry_count", 0) >= state.get("max_retries", 3):
        logger.error("[Validator] Max retries exceeded; routing to summarize with error")
        return "fail"
    return "retry"

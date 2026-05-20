# ─────────────────────────────────────────────
# project/executor.py
#
# Orchestrates the full prompt-chaining pipeline:
#   1. Decompose  (LLM call 1)
#   2. Generate   (LLM call 2)
#   3. Validate   (rule-based)
#   4. Execute    (DB)
#   5. Fix/Retry  (LLM call 3, max 1 retry)
#   6. Log & Return structured result
# ─────────────────────────────────────────────
from __future__ import annotations
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from typing import Any

from database import execute_query
from logger import get_logger, log_execution
from sql_generator import decompose, fix_sql, generate_sql
from validator import ValidationError, validate_sql

logger = get_logger("pipeline")


def run_pipeline(question: str) -> dict[str, Any]:
    """Execute the full Text-to-SQL pipeline for *question*.

    Parameters
    ----------
    question : str
        Natural-language question from the user.

    Returns
    -------
    dict with keys:
        question        – original question
        decomposition   – structured JSON from step 1
        sql             – final SQL used (possibly corrected)
        result          – list of row dicts (empty on failure)
        status          – "success" | "failed"
        retry_attempted – bool
        retry_succeeded – bool
        error           – error message string (empty on success)
    """
    logger.info("Pipeline start: %s", question)
    output: dict[str, Any] = {
        "question":        question,
        "decomposition":   {},
        "sql":             "",
        "result":          [],
        "status":          "failed",
        "retry_attempted": False,
        "retry_succeeded": False,
        "error":           "",
    }

    # ── Step 1: Decompose ─────────────────────────────────────────────────────
    try:
        decomposition = decompose(question)
        output["decomposition"] = decomposition
    except Exception as exc:
        output["error"] = f"Decomposition failed: {exc}"
        logger.exception("Decomposition failed")
        log_execution(output)
        return output

    # ── Step 2: Generate SQL ──────────────────────────────────────────────────
    try:
        sql = generate_sql(decomposition)
        output["sql"] = sql
    except Exception as exc:
        output["error"] = f"SQL generation failed: {exc}"
        logger.exception("SQL generation failed")
        log_execution(output)
        return output

    # ── Step 3: Validate ──────────────────────────────────────────────────────
    try:
        validate_sql(sql)
    except ValidationError as exc:
        output["error"] = f"Validation blocked query: {exc}"
        logger.warning("Validation blocked query: %s", exc)
        log_execution(output)
        return output

    # ── Step 4: Execute ───────────────────────────────────────────────────────
    try:
        rows = execute_query(sql)
        output["result"] = rows
        output["status"] = "success"
        logger.info("Query succeeded (%d rows)", len(rows))
        log_execution(output)
        return output
    except Exception as first_exc:
        logger.warning("First execution failed: %s", first_exc)
        first_error_msg = str(first_exc)

    # ── Step 5: Retry / Self-Correction (max 1 attempt) ──────────────────────
    output["retry_attempted"] = True

    try:
        fixed_sql = fix_sql(sql, first_error_msg)
    except Exception as fix_exc:
        output["error"] = (
            f"Original execution error: {first_error_msg}\n"
            f"Fix-generation also failed: {fix_exc}"
        )
        log_execution(output)
        return output

    # Validate the fixed SQL as well
    try:
        validate_sql(fixed_sql)
    except ValidationError as exc:
        output["error"] = (
            f"Original execution error: {first_error_msg}\n"
            f"Fixed SQL failed validation: {exc}"
        )
        log_execution(output)
        return output

    output["sql"] = fixed_sql  # Update to corrected version

    try:
        rows = execute_query(fixed_sql)
        output["result"] = rows
        output["status"] = "success"
        output["retry_succeeded"] = True
        logger.info("Retry succeeded (%d rows)", len(rows))
        log_execution(output)
        return output
    except Exception as second_exc:
        logger.error("Retry failed: %s", second_exc)
        output["error"] = (
            f"Original error: {first_error_msg}\n"
            f"Retry also failed: {second_exc}"
        )
        log_execution(output)
        return output
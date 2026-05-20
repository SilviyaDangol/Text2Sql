"""SQL generator agent: produces PostgreSQL from plan and schema."""

from __future__ import annotations

import re
from typing import Any

from app.agents.llm import invoke_llm
from app.config import logger
from app.prompts import SQL_GENERATOR_SYSTEM_PROMPT, sql_generator_user_prompt
from app.tools.db_tools import fetch_schema_summary


def _extract_sql(raw: str) -> str:
    """Strip markdown fences and surrounding prose from LLM output."""
    text = raw.strip()
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    lines = [line for line in text.splitlines() if not line.strip().startswith("--")]
    text = "\n".join(lines).strip()
    if ";" in text:
        text = text.split(";")[0].strip()
    return text


def run_sql_generator(state: dict[str, Any]) -> dict[str, Any]:
    """Generate PostgreSQL SELECT from plan and optional validation feedback."""
    user_query = state.get("user_query", "")
    plan = state.get("plan", "")
    schema_summary = state.get("schema_summary") or fetch_schema_summary()
    previous_sql = state.get("generated_sql") or None
    feedback = state.get("validation_feedback") or state.get("execution_error")

    retry_count = state.get("retry_count", 0)
    logger.info(
        "[SQL Generator] Starting | retry=%d has_feedback=%s",
        retry_count,
        bool(feedback),
    )

    try:
        raw = invoke_llm(
            SQL_GENERATOR_SYSTEM_PROMPT,
            sql_generator_user_prompt(
                user_query=user_query,
                plan=plan,
                schema_summary=schema_summary,
                previous_sql=previous_sql,
                feedback=feedback,
            ),
        )
        sql = _extract_sql(raw)
        logger.info("[SQL Generator] SQL generated | sql=%s", sql[:200])
        return {
            "generated_sql": sql,
            "is_valid_sql": False,
            "validation_feedback": None,
        }
    except Exception as exc:
        logger.exception("[SQL Generator] Failed: %s", exc)
        errors = list(state.get("errors", []))
        errors.append(f"SQL generator error: {exc}")
        return {"generated_sql": "", "errors": errors}

"""Summarizer agent: natural language answer from query results."""

from __future__ import annotations

from typing import Any

from app.agents.llm import invoke_llm
from app.config import logger
from app.prompts import SUMMARIZER_SYSTEM_PROMPT, summarizer_user_prompt
from app.tools.db_tools import results_to_json_string


def run_summarizer(state: dict[str, Any]) -> dict[str, Any]:
    """Convert execution results into a user-friendly answer."""
    user_query = state.get("user_query", "")
    sql = state.get("generated_sql", "")
    results = state.get("execution_results") or {}
    errors = state.get("errors", [])

    logger.info("[Summarizer] Starting")

    if not state.get("is_valid_sql") and state.get("retry_count", 0) >= state.get("max_retries", 3):
        msg = (
            "I could not produce a valid read-only SQL query for your question. "
            f"Details: {'; '.join(errors) if errors else state.get('validation_feedback', 'Validation failed')}"
        )
        logger.warning("[Summarizer] Returning validation failure message")
        return {"final_answer": msg}

    if results and not results.get("success"):
        exec_err = state.get("execution_error") or results.get("error")
        if state.get("retry_count", 0) >= state.get("max_retries", 3):
            msg = (
                "The query could not be executed successfully after several attempts. "
                f"Last error: {exec_err}"
            )
            logger.warning("[Summarizer] Returning execution failure message")
            return {"final_answer": msg}

    try:
        results_json = results_to_json_string(results)
        answer = invoke_llm(
            SUMMARIZER_SYSTEM_PROMPT,
            summarizer_user_prompt(user_query, sql, results_json),
        )
        logger.info("[Summarizer] Answer generated | length=%d", len(answer))
        return {"final_answer": answer}
    except Exception as exc:
        logger.exception("[Summarizer] Failed: %s", exc)
        fallback = _fallback_summary(user_query, results)
        return {"final_answer": fallback, "errors": errors + [f"Summarizer error: {exc}"]}


def _fallback_summary(user_query: str, results: dict[str, Any]) -> str:
    """Non-LLM fallback when summarization fails."""
    count = results.get("row_count", 0)
    if count == 0:
        return f"No results found for: {user_query}"
    rows = results.get("rows", [])[:5]
    return f"Found {count} row(s). Sample: {rows}"

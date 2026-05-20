"""Planner agent: analyzes user query and schema to produce an execution plan."""

from __future__ import annotations

from typing import Any

from app.agents.llm import invoke_llm
from app.config import logger
from app.prompts import PLANNER_SYSTEM_PROMPT, planner_user_prompt
from app.tools.db_tools import fetch_schema_summary


def run_planner(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze the user query and produce a strategic SQL plan."""
    user_query = state.get("user_query", "")
    logger.info("[Planner] Starting | query=%r", user_query[:120])

    try:
        schema_summary = fetch_schema_summary()
        plan = invoke_llm(
            PLANNER_SYSTEM_PROMPT,
            planner_user_prompt(user_query, schema_summary),
        )
        logger.info("[Planner] Plan created | length=%d", len(plan))
        return {
            "plan": plan,
            "schema_summary": schema_summary,
            "errors": [],
        }
    except Exception as exc:
        logger.exception("[Planner] Failed: %s", exc)
        return {
            "plan": "",
            "errors": [f"Planner error: {exc}"],
        }

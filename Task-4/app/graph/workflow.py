"""LangGraph state machine for the Text-to-SQL agentic pipeline."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents.executor import executor_decision, run_executor
from app.agents.planner import run_planner
from app.agents.sql_generator import run_sql_generator
from app.agents.summarizer import run_summarizer
from app.agents.validator import run_validator, validator_decision
from app.config import logger, settings


def _merge_errors(existing: list[str], new: dict[str, Any]) -> list[str]:
    merged = list(existing or [])
    merged.extend(new.get("errors") or [])
    return merged


class AgentState(TypedDict, total=False):
    """Workflow state tracked across all agents."""

    user_query: str
    plan: str
    schema_summary: str
    generated_sql: str
    is_valid_sql: bool
    validation_feedback: str | None
    execution_results: dict[str, Any]
    execution_error: str | None
    final_answer: str
    errors: list[str]
    retry_count: int
    max_retries: int


def _wrap(node_fn):
    """Log node entry/exit for evaluation traceability."""

    def inner(state: AgentState) -> dict[str, Any]:
        name = node_fn.__name__
        logger.info("=== Workflow node: %s ===", name)
        result = node_fn(state)
        logger.info("=== Completed node: %s | keys=%s ===", name, list(result.keys()))
        return result

    return inner


def build_workflow() -> StateGraph:
    """Construct the LangGraph workflow with validation/execution retry loops."""
    graph = StateGraph(AgentState)

    graph.add_node("planner", _wrap(run_planner))
    graph.add_node("sql_generator", _wrap(run_sql_generator))
    graph.add_node("validator", _wrap(run_validator))
    graph.add_node("executor", _wrap(run_executor))
    graph.add_node("summarizer", _wrap(run_summarizer))

    graph.set_entry_point("planner")
    graph.add_edge("planner", "sql_generator")
    graph.add_edge("sql_generator", "validator")

    graph.add_conditional_edges(
        "validator",
        validator_decision,
        {
            "execute": "executor",
            "retry": "sql_generator",
            "fail": "summarizer",
        },
    )

    graph.add_conditional_edges(
        "executor",
        executor_decision,
        {
            "summarize": "summarizer",
            "retry": "sql_generator",
            "fail": "summarizer",
        },
    )

    graph.add_edge("summarizer", END)
    return graph


_compiled_graph = None


def get_compiled_workflow():
    """Return singleton compiled graph."""
    global _compiled_graph
    if _compiled_graph is None:
        logger.info("Compiling LangGraph workflow")
        _compiled_graph = build_workflow().compile()
    return _compiled_graph


def run_workflow(user_query: str) -> AgentState:
    """
    Execute the full Text-to-SQL pipeline for a natural language query.

    Evaluation trace (logged to logs/app.log):
    - Understanding: planner decomposition
    - Implementation: SQL generation + validation
    - Agent behavior: retry on validation/execution failure
    """
    logger.info("========== Workflow START ==========")
    logger.info("User query: %s", user_query)

    initial: AgentState = {
        "user_query": user_query,
        "plan": "",
        "generated_sql": "",
        "is_valid_sql": False,
        "validation_feedback": None,
        "execution_results": {},
        "execution_error": None,
        "final_answer": "",
        "errors": [],
        "retry_count": 0,
        "max_retries": settings.max_sql_retries,
    }

    try:
        final_state: AgentState = get_compiled_workflow().invoke(initial)
    except Exception as exc:
        logger.exception("Workflow failed: %s", exc)
        final_state = {
            **initial,
            "final_answer": f"Workflow error: {exc}",
            "errors": [str(exc)],
        }

    logger.info(
        "========== Workflow END ========== | valid=%s retries=%s",
        final_state.get("is_valid_sql"),
        final_state.get("retry_count"),
    )
    logger.info("Final answer preview: %s", (final_state.get("final_answer") or "")[:300])
    return final_state


def run_workflow_traced(user_query: str) -> tuple[AgentState, list[dict[str, Any]]]:
    """
    Run the pipeline and return the final state plus per-node trace steps.

    Each trace entry: {node, generated_sql, is_valid_sql, validation_feedback,
    execution_error, retry_count, execution_success, row_count}.
    """
    logger.info("========== Workflow START (traced) ==========")
    logger.info("User query: %s", user_query)

    initial: AgentState = {
        "user_query": user_query,
        "plan": "",
        "generated_sql": "",
        "is_valid_sql": False,
        "validation_feedback": None,
        "execution_results": {},
        "execution_error": None,
        "final_answer": "",
        "errors": [],
        "retry_count": 0,
        "max_retries": settings.max_sql_retries,
    }

    trace: list[dict[str, Any]] = []
    final_state: AgentState = dict(initial)

    try:
        graph = get_compiled_workflow()
        for chunk in graph.stream(initial, stream_mode="updates"):
            for node, update in chunk.items():
                merged = {**final_state, **update}
                final_state = merged  # type: ignore[assignment]
                results = update.get("execution_results") or {}
                trace.append(
                    {
                        "node": node,
                        "generated_sql": update.get("generated_sql") or final_state.get("generated_sql"),
                        "is_valid_sql": update.get("is_valid_sql", final_state.get("is_valid_sql")),
                        "validation_feedback": update.get("validation_feedback"),
                        "execution_error": update.get("execution_error"),
                        "retry_count": update.get("retry_count", final_state.get("retry_count", 0)),
                        "execution_success": results.get("success"),
                        "row_count": results.get("row_count"),
                        "errors": update.get("errors"),
                    }
                )
    except Exception as exc:
        logger.exception("Workflow failed: %s", exc)
        final_state = {
            **initial,
            "final_answer": f"Workflow error: {exc}",
            "errors": [str(exc)],
        }
        trace.append({"node": "workflow_error", "errors": [str(exc)]})

    logger.info(
        "========== Workflow END (traced) ========== | valid=%s retries=%s",
        final_state.get("is_valid_sql"),
        final_state.get("retry_count"),
    )
    return final_state, trace

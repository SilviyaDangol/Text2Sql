"""FastAPI entry point for the Text-to-SQL agentic workflow."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import APP_LOG_PATH, logger, settings
from app.db import check_database_connection
from app.graph.workflow import run_workflow

app = FastAPI(
    title="Text-to-SQL Agent API",
    description="Agentic natural language to PostgreSQL query pipeline",
    version="1.0.0",
)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language question")


class QueryResponse(BaseModel):
    answer: str
    plan: str | None = None
    sql: str | None = None
    is_valid_sql: bool = False
    row_count: int = 0
    errors: list[str] = Field(default_factory=list)
    execution_results: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    database: bool
    log_file: str


@app.on_event("startup")
async def startup() -> None:
    logger.info("API starting | host=%s port=%s", settings.api_host, settings.api_port)
    check_database_connection()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_ok = check_database_connection()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        database=db_ok,
        log_file=str(APP_LOG_PATH),
    )


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """Run the full agent workflow for a natural language question."""
    logger.info("API /query received | query=%r", request.query[:120])

    try:
        state = run_workflow(request.query)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    results = state.get("execution_results") or {}
    return QueryResponse(
        answer=state.get("final_answer") or "No answer generated.",
        plan=state.get("plan"),
        sql=state.get("generated_sql"),
        is_valid_sql=bool(state.get("is_valid_sql")),
        row_count=results.get("row_count", 0),
        errors=state.get("errors") or [],
        execution_results=results if results else None,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )

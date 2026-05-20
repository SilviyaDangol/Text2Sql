#!/usr/bin/env python3
"""
Run the Text-to-SQL pipeline against sql_questions_only benchmark CSV.

Outputs (under --output-dir, default: evaluation_outputs/):
  - generated_sql.jsonl       Per-question generated SQL and metadata
  - execution_logs.jsonl        Per-node workflow trace and execution details
  - evaluation_results.csv      Summary table for grading / reporting
  - metrics_summary.json        Aggregate evaluation metrics
  - EVALUATION_REPORT.md        Architecture notes + example success/failure cases
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Repo root on PYTHONPATH (parent of app/)
REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
sys.path.insert(0, str(REPO_ROOT))

# Load app/.env before config; allow console-only logging for benchmark runs
from dotenv import load_dotenv

load_dotenv(APP_DIR / ".env")
import os

os.environ.setdefault("BENCHMARK_CONSOLE_LOG_ONLY", "1")

# When running on the host, docker-compose exposes Postgres on localhost:5433
db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5433/classicmodels",
)
if "@db:" in db_url or "@db/" in db_url:
    db_url = db_url.replace("@db:5432", "@localhost:5433").replace("@db/", "@localhost:5433/")
    os.environ["DATABASE_URL"] = db_url

from app.config import setup_logging, settings  # noqa: E402
from app.db import check_database_connection  # noqa: E402
from app.graph.workflow import run_workflow_traced  # noqa: E402
from app.tools.db_tools import execute_read_query  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from eval_metrics import execution_accuracy, schema_linking_accuracy  # noqa: E402

DEFAULT_CSV = REPO_ROOT / "sql_questions_only - .csv"
DEFAULT_REFERENCE = REPO_ROOT / "sql_reference_answers.csv"
DEFAULT_OUTPUT = REPO_ROOT / "evaluation_outputs"


def load_questions(csv_path: Path) -> list[str]:
    """Load natural-language questions from the benchmark CSV."""
    questions: list[str] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "question" in (reader.fieldnames or []):
            for row in reader:
                q = (row.get("question") or "").strip()
                if q:
                    questions.append(q)
        else:
            f.seek(0)
            raw = csv.reader(f)
            header = next(raw, None)
            start = 1 if header and header[0].lower() == "question" else 0
            if header and start == 0:
                q0 = (header[0] or "").strip()
                if q0 and q0.lower() != "question":
                    questions.append(q0)
            for row in raw:
                if row and row[0].strip():
                    questions.append(row[0].strip())
    return questions


def load_reference_sql(csv_path: Path) -> dict[str, str]:
    """Load question -> golden SQL mapping."""
    mapping: dict[str, str] = {}
    if not csv_path.exists():
        return mapping
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = (row.get("question") or "").strip()
            sql = (row.get("correct_sql") or "").strip()
            if q and sql:
                mapping[q] = sql
    return mapping


def attach_golden_metrics(
    records: list[dict[str, Any]], reference: dict[str, str]
) -> None:
    """Compute execution + schema linking accuracy vs reference SQL."""
    for rec in records:
        question = rec["question"]
        rec["correct_sql"] = reference.get(question, "")
        ref_sql = rec["correct_sql"]
        gen_sql = rec.get("generated_sql") or ""

        if ref_sql:
            ref_result = execute_read_query(ref_sql)
        else:
            ref_result = {"success": False, "rows": []}

        if gen_sql:
            gen_result = execute_read_query(gen_sql)
        else:
            gen_result = {"success": False, "rows": []}

        rec["reference_executed"] = bool(ref_result.get("success"))
        rec["execution_accuracy"] = execution_accuracy(ref_result, gen_result)
        rec["schema_linking_accuracy"] = schema_linking_accuracy(ref_sql, gen_sql)


def write_comparison_csv(path: Path, records: list[dict[str, Any]]) -> None:
    """Full benchmark CSV: question, correct SQL, generated SQL, B metrics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "question",
        "correct_sql",
        "generated_sql",
        "execution_accuracy",
        "schema_linking_accuracy",
        "executed_successfully",
        "retry_needed",
        "final_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "question": r["question"],
                    "correct_sql": r.get("correct_sql", ""),
                    "generated_sql": r.get("generated_sql", ""),
                    "execution_accuracy": r.get("execution_accuracy", 0),
                    "schema_linking_accuracy": r.get("schema_linking_accuracy", 0),
                    "executed_successfully": "Yes" if r.get("executed_successfully") else "No",
                    "retry_needed": "Yes" if r.get("retry_needed") else "No",
                    "final_status": r.get("final_status", ""),
                }
            )


def infer_correct_result(question: str, state: dict[str, Any]) -> str:
    """
    Heuristic correctness when no golden SQL is provided in the CSV.

    Returns: yes | no | manual
    """
    results = state.get("execution_results") or {}
    if not results.get("success") or not state.get("is_valid_sql"):
        return "no"

    row_count = int(results.get("row_count") or 0)
    q = question.lower().strip()

    scalar_hints = (
        "total number",
        "count total",
        "total revenue",
        "total quantity",
        "average ",
        "max ",
        "min ",
        "number of employees",
    )
    if any(h in q for h in scalar_hints) and " per " not in q:
        return "yes" if row_count >= 1 else "no"

    if " per " in q:
        return "yes" if row_count >= 1 else "no"

    list_hints = ("list ", "get all", "show all", "get ", "show ")
    if any(q.startswith(h) for h in list_hints):
        return "yes" if row_count > 0 else "no"

    return "yes" if row_count > 0 else "manual"


def format_correct_result(correct: str, retry_needed: bool, executed: bool) -> str:
    """Display value for the Correct Result column."""
    if retry_needed and executed and correct in ("yes", "manual"):
        return "Fixed After Retry"
    if correct == "yes":
        return "Yes"
    if correct == "manual":
        return "Manual Review"
    return "No"


def final_status(state: dict[str, Any], executed: bool, correct: str) -> str:
    """Map run outcome to Success | Failed | Partial."""
    if executed and correct in ("yes", "manual"):
        return "Success"
    if state.get("is_valid_sql") and not executed:
        return "Partial"
    return "Failed"


def evaluate_one(question: str, index: int, use_trace: bool) -> dict[str, Any]:
    """Run pipeline for a single question and collect evaluation record."""
    t0 = time.perf_counter()
    if use_trace:
        state, trace = run_workflow_traced(question)
    else:
        from app.graph.workflow import run_workflow

        state = run_workflow(question)
        trace = []

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    results = state.get("execution_results") or {}
    executed = bool(results.get("success"))
    correct = infer_correct_result(question, state)
    retries = int(state.get("retry_count") or 0)
    retry_needed = retries > 0
    status = final_status(state, executed, correct)
    correct_display = format_correct_result(correct, retry_needed, executed)

    sql_attempts = [
        step.get("generated_sql")
        for step in trace
        if step.get("node") == "sql_generator" and step.get("generated_sql")
    ]

    return {
        "index": index,
        "question": question,
        "generated_sql": state.get("generated_sql") or "",
        "plan": state.get("plan") or "",
        "executed_successfully": executed,
        "correct_result": correct,
        "correct_result_display": correct_display,
        "retry_needed": retry_needed,
        "retry_count": retries,
        "final_status": status,
        "is_valid_sql": bool(state.get("is_valid_sql")),
        "row_count": results.get("row_count", 0),
        "columns": results.get("columns", []),
        "execution_error": state.get("execution_error") or results.get("error"),
        "validation_feedback": state.get("validation_feedback"),
        "errors": state.get("errors") or [],
        "final_answer": state.get("final_answer") or "",
        "latency_ms": latency_ms,
        "trace": trace,
        "sql_attempts": sql_attempts,
        "sample_rows": (results.get("rows") or [])[:3],
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, default=str) + "\n")


def write_results_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "Question",
        "Generated SQL",
        "Executed Successfully",
        "Correct Result",
        "Retry Needed",
        "Retry Count",
        "Final Status",
        "Row Count",
        "Latency Ms",
        "Is Valid SQL",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "Question": r["question"],
                    "Generated SQL": r["generated_sql"],
                    "Executed Successfully": "Yes" if r["executed_successfully"] else "No",
                    "Correct Result": r.get("correct_result_display")
                    or r["correct_result"].capitalize(),
                    "Retry Needed": "Yes" if r["retry_needed"] else "No",
                    "Retry Count": r["retry_count"],
                    "Final Status": r["final_status"],
                    "Row Count": r["row_count"],
                    "Latency Ms": r["latency_ms"],
                    "Is Valid SQL": "Yes" if r["is_valid_sql"] else "No",
                }
            )


def compute_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records) or 1
    executed = sum(1 for r in records if r["executed_successfully"])
    correct_yes = sum(1 for r in records if r["correct_result"] == "yes")
    retries = sum(1 for r in records if r["retry_needed"])
    retry_success = sum(
        1
        for r in records
        if r.get("correct_result_display") == "Fixed After Retry"
    )
    failed = sum(1 for r in records if r["final_status"] == "Failed")
    latencies = [r["latency_ms"] for r in records]

    exec_acc = [r.get("execution_accuracy", 0) for r in records if "execution_accuracy" in r]
    schema_acc = [r.get("schema_linking_accuracy", 0) for r in records if "schema_linking_accuracy" in r]

    metrics = {
        "total_questions": len(records),
        "sql_execution_success_rate": round(executed / n, 4),
        "heuristic_correct_result_rate": round(correct_yes / n, 4),
        "execution_accuracy_avg": round(sum(exec_acc) / max(len(exec_acc), 1), 4),
        "schema_linking_accuracy_avg": round(sum(schema_acc) / max(len(schema_acc), 1), 4),
        "retry_needed_count": retries,
        "retry_self_correction_success_rate": round(retry_success / max(retries, 1), 4),
        "failed_query_count": failed,
        "success_count": sum(1 for r in records if r["final_status"] == "Success"),
        "partial_count": sum(1 for r in records if r["final_status"] == "Partial"),
        "avg_latency_ms": round(sum(latencies) / n, 2),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * (n - 1))], 2) if latencies else 0,
        "note": (
            "execution_accuracy: 1.0 when generated query result set matches reference SQL. "
            "schema_linking_accuracy: F1 over tables+columns vs reference SQL."
        ),
    }
    return metrics


def pick_examples(
    records: list[dict[str, Any]], *, success: bool, limit: int = 3
) -> list[dict[str, Any]]:
    if success:
        pool = [r for r in records if r["final_status"] == "Success" and not r["retry_needed"]]
        if len(pool) < limit:
            pool.extend(
                r
                for r in records
                if r["final_status"] == "Success" and r["retry_needed"] and r not in pool
            )
    else:
        pool = [r for r in records if r["final_status"] == "Failed"]
        if len(pool) < limit:
            pool.extend(r for r in records if r["final_status"] == "Partial" and r not in pool)

    out = []
    for r in pool[:limit]:
        out.append(
            {
                "question": r["question"],
                "generated_sql": r["generated_sql"],
                "executed_successfully": r["executed_successfully"],
                "retry_count": r["retry_count"],
                "sql_attempts": r["sql_attempts"],
                "execution_error": r["execution_error"],
                "validation_feedback": r["validation_feedback"],
                "final_answer_preview": (r["final_answer"] or "")[:400],
                "sample_rows": r["sample_rows"],
            }
        )
    return out


def write_report(
    path: Path,
    metrics: dict[str, Any],
    success_examples: list[dict[str, Any]],
    failure_examples: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    report = f"""# Text-to-SQL Benchmark Evaluation Report

Generated: {datetime.now(timezone.utc).isoformat()}

## Pipeline architecture

```mermaid
flowchart LR
    Q[Benchmark Question] --> P[Planner]
    P --> G[SQL Generator]
    G --> V[Validator]
    V -->|valid| E[Executor]
    V -->|invalid| G
    E -->|success| S[Summarizer]
    E -->|error| G
    S --> R[Final Answer + Results]
```

### Design decisions

1. **LangGraph orchestration** — Each stage (planner, SQL generator, validator, executor, summarizer) is an isolated node with explicit routing. This makes retries and evaluation traces reproducible.
2. **Planner-first decomposition** — The planner inspects the live `information_schema` summary before SQL generation, improving table/column selection on join and aggregate questions.
3. **Validator gate** — `sqlparse` syntax checks and read-only keyword guards run before any database call, reducing unsafe or multi-statement SQL.
4. **Execution retry loop** — Failed validation or PostgreSQL errors increment `retry_count` and route back to the SQL generator with feedback (validation message or execution error).
5. **Bounded result sets** — The executor appends `LIMIT {{sql_row_limit}}` when missing, keeping benchmark runs fast and logs small.
6. **Evaluation without golden SQL** — The benchmark CSV lists questions only. This script marks **Correct Result** using execution success plus row-count heuristics; join-heavy answers should be spot-checked manually or compared to a reference SQL file.

## Output artifacts

| File | Description |
|------|-------------|
| `generated_sql.jsonl` | Question, plan, final SQL, latency, status |
| `execution_logs.jsonl` | Per-question workflow trace and errors |
| `evaluation_results.csv` | Summary table (Question, SQL, success flags, retries) |
| `benchmark_comparison.csv` | question, correct_sql, generated_sql, execution_accuracy, schema_linking_accuracy |
| `metrics_summary.json` | Aggregate rates and latency stats |
| `examples_success.json` | Sample successful runs |
| `examples_failed.json` | Sample failures and retry behavior |

## Metrics summary

```json
{json.dumps(metrics, indent=2)}
```

## Example successful queries

```json
{json.dumps(success_examples, indent=2, default=str)}
```

## Example failed / retry cases

```json
{json.dumps(failure_examples, indent=2, default=str)}
```

### Retry handling behavior

- **Validation retry** — Invalid syntax, non-SELECT statements, or forbidden keywords send feedback to the SQL generator without hitting the database.
- **Execution retry** — PostgreSQL errors (missing column, bad join, etc.) append the error to state and regenerate SQL until `MAX_SQL_RETRIES` (default {settings.max_sql_retries}).
- **Terminal failure** — After max retries, the summarizer returns an error-focused natural language message; the evaluation row is marked **Failed** or **Partial**.

## How to reproduce

```bash
cd {REPO_ROOT / "app"}
# Ensure DB is up and .env has LLM keys
docker compose up -d db
export PYTHONPATH="{REPO_ROOT}"
python ../scripts/run_benchmark_evaluation.py --limit 5   # smoke test
python ../scripts/run_benchmark_evaluation.py             # full 50 questions
```

All artifacts written to: `{output_dir}`
"""
    path.write_text(report, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Text-to-SQL on benchmark CSV")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Path to sql_questions_only CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for evaluation artifacts",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max questions (0 = all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N questions")
    parser.add_argument("--no-trace", action="store_true", help="Disable per-node trace capture")
    parser.add_argument(
        "--check-db-only",
        action="store_true",
        help="Verify database connectivity and exit",
    )
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=DEFAULT_REFERENCE,
        help="Golden SQL CSV (question, correct_sql)",
    )
    args = parser.parse_args()

    logger = setup_logging("benchmark")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.csv.exists():
        logger.error("CSV not found: %s", args.csv)
        return 1

    if not check_database_connection():
        logger.error(
            "Database unreachable. Start Postgres (e.g. cd app && docker compose up -d db) "
            "and set DATABASE_URL in app/.env"
        )
        return 1

    if args.check_db_only:
        logger.info("Database OK")
        return 0

    questions = load_questions(args.csv)
    if args.offset:
        questions = questions[args.offset :]
    if args.limit > 0:
        questions = questions[: args.limit]

    reference = load_reference_sql(args.reference_csv)
    if not reference:
        logger.warning("No reference SQL loaded from %s", args.reference_csv)

    logger.info(
        "Starting benchmark | questions=%d csv=%s reference=%d output=%s",
        len(questions),
        args.csv,
        len(reference),
        out_dir,
    )

    records: list[dict[str, Any]] = []
    for i, question in enumerate(questions, start=1 + args.offset):
        logger.info("--- [%d/%d] %s ---", i - args.offset, len(questions), question[:80])
        try:
            rec = evaluate_one(question, i, use_trace=not args.no_trace)
        except Exception as exc:
            logger.exception("Question failed: %s", exc)
            rec = {
                "index": i,
                "question": question,
                "generated_sql": "",
                "plan": "",
                "executed_successfully": False,
                "correct_result": "no",
                "retry_needed": False,
                "retry_count": 0,
                "final_status": "Failed",
                "is_valid_sql": False,
                "row_count": 0,
                "columns": [],
                "execution_error": str(exc),
                "validation_feedback": None,
                "errors": [str(exc)],
                "final_answer": "",
                "latency_ms": 0,
                "trace": [],
                "sql_attempts": [],
                "sample_rows": [],
            }
        records.append(rec)

        # Incremental flush so partial runs are preserved
        attach_golden_metrics(records, reference)
        write_jsonl(out_dir / "generated_sql.jsonl", records)
        write_results_csv(out_dir / "evaluation_results.csv", records)
        write_comparison_csv(out_dir / "benchmark_comparison.csv", records)

    attach_golden_metrics(records, reference)

    sql_records = [
        {
            "index": r["index"],
            "question": r["question"],
            "plan": r["plan"],
            "generated_sql": r["generated_sql"],
            "sql_attempts": r["sql_attempts"],
            "final_status": r["final_status"],
            "latency_ms": r["latency_ms"],
        }
        for r in records
    ]
    write_jsonl(out_dir / "generated_sql.jsonl", sql_records)

    log_records = [
        {
            "index": r["index"],
            "question": r["question"],
            "trace": r["trace"],
            "errors": r["errors"],
            "execution_error": r["execution_error"],
            "validation_feedback": r["validation_feedback"],
            "executed_successfully": r["executed_successfully"],
            "row_count": r["row_count"],
            "sample_rows": r["sample_rows"],
        }
        for r in records
    ]
    write_jsonl(out_dir / "execution_logs.jsonl", log_records)

    write_results_csv(out_dir / "evaluation_results.csv", records)
    write_comparison_csv(out_dir / "benchmark_comparison.csv", records)

    # Stable copy at evaluation_outputs root for submission
    write_comparison_csv(args.output_dir / "benchmark_comparison.csv", records)

    metrics = compute_metrics(records)
    metrics["run_id"] = run_id
    metrics["csv_path"] = str(args.csv)
    metrics["llm_provider"] = settings.llm_provider
    (out_dir / "metrics_summary.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )

    success_ex = pick_examples(records, success=True)
    failure_ex = pick_examples(records, success=False)
    (out_dir / "examples_success.json").write_text(
        json.dumps(success_ex, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "examples_failed.json").write_text(
        json.dumps(failure_ex, indent=2, default=str), encoding="utf-8"
    )

    write_report(
        out_dir / "EVALUATION_REPORT.md",
        metrics,
        success_ex,
        failure_ex,
        out_dir,
    )

    # Symlink latest run at output-dir root for convenience
    latest = args.output_dir / "latest"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(out_dir.name, target_is_directory=True)

    logger.info("Benchmark complete | output=%s", out_dir)
    logger.info("Metrics: %s", json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

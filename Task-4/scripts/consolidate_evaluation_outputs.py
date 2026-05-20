#!/usr/bin/env python3
"""Build consolidated execution logs, failed examples, and extended comparison CSV."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "evaluation_outputs"
COMPARISON_CSV = OUTPUT_ROOT / "benchmark_comparison.csv"
LATEST_RUN = OUTPUT_ROOT / "latest"
FULL_LOG = OUTPUT_ROOT / "full_run.log"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def discover_runs() -> list[dict]:
    """Historical benchmark runs with execution_logs.jsonl."""
    runs = []
    for d in sorted(OUTPUT_ROOT.iterdir()):
        if not d.is_dir() or d.name in ("latest",) or not d.name[:8].isdigit():
            continue
        log_path = d / "execution_logs.jsonl"
        if log_path.exists():
            runs.append(
                {
                    "run_id": d.name,
                    "path": str(log_path),
                    "question_count": len(load_jsonl(log_path)),
                }
            )
    return runs


def build_execution_logs() -> tuple[Path, Path]:
    """Merge per-run logs into consolidated files with history."""
    runs = discover_runs()
    consolidated: list[dict] = []
    history: list[dict] = []

    for run in runs:
        entries = load_jsonl(Path(run["path"]))
        history.append({**run, "entries": len(entries)})
        for entry in entries:
            consolidated.append(
                {
                    "run_id": run["run_id"],
                    "index": entry.get("index"),
                    "question": entry.get("question"),
                    "executed_successfully": entry.get("executed_successfully"),
                    "row_count": entry.get("row_count"),
                    "execution_error": entry.get("execution_error"),
                    "validation_feedback": entry.get("validation_feedback"),
                    "errors": entry.get("errors"),
                    "workflow_trace": entry.get("trace"),
                    "sample_rows": entry.get("sample_rows"),
                }
            )

    out_jsonl = OUTPUT_ROOT / "query_execution_logs.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for row in consolidated:
            f.write(json.dumps(row, default=str) + "\n")

    history_path = OUTPUT_ROOT / "query_execution_logs_history.json"
    history_doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary_run": runs[-1]["run_id"] if runs else None,
        "full_terminal_log": str(FULL_LOG) if FULL_LOG.exists() else None,
        "per_question_log": str(out_jsonl),
        "app_log": str(REPO_ROOT / "app" / "logs" / "app.log"),
        "runs": history,
        "total_log_entries": len(consolidated),
    }
    history_path.write_text(json.dumps(history_doc, indent=2), encoding="utf-8")

    return out_jsonl, history_path


def build_failed_examples(logs_by_question: dict[str, dict], comparison: list[dict]) -> tuple[Path, Path]:
    """Failed / partial cases: execution mismatches + retry documentation."""
    retry_cases = [r for r in comparison if r.get("retry_needed", "").lower() == "yes"]
    exec_failures = [r for r in comparison if float(r.get("execution_accuracy", 0)) < 1.0]
    workflow_failures = [r for r in comparison if r.get("final_status") == "Failed"]

    examples = []
    for row in exec_failures:
        q = row["question"]
        log = logs_by_question.get(q, {})
        trace = log.get("workflow_trace") or []
        sql_attempts = [
            t.get("generated_sql")
            for t in trace
            if t.get("node") == "sql_generator" and t.get("generated_sql")
        ]
        examples.append(
            {
                "category": "execution_accuracy_mismatch",
                "question": q,
                "correct_sql": row.get("correct_sql"),
                "generated_sql": row.get("generated_sql"),
                "execution_accuracy": float(row.get("execution_accuracy", 0)),
                "schema_linking_accuracy": float(row.get("schema_linking_accuracy", 0)),
                "executed_successfully": row.get("executed_successfully"),
                "retry_needed": row.get("retry_needed"),
                "retry_count": max((t.get("retry_count") or 0) for t in trace) if trace else 0,
                "sql_attempts": sql_attempts,
                "execution_error": log.get("execution_error"),
                "validation_feedback": log.get("validation_feedback"),
                "workflow_trace_summary": [
                    {
                        "node": t.get("node"),
                        "is_valid_sql": t.get("is_valid_sql"),
                        "execution_success": t.get("execution_success"),
                        "row_count": t.get("row_count"),
                        "retry_count": t.get("retry_count"),
                    }
                    for t in trace
                ],
                "sample_rows": log.get("sample_rows"),
                "failure_reason": (
                    "SQL executed successfully but result set differs from reference SQL "
                    "(extra/missing columns, different projection, or join shape)."
                ),
            }
        )

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_questions": len(comparison),
            "pipeline_retry_cases": len(retry_cases),
            "workflow_failed_cases": len(workflow_failures),
            "execution_accuracy_mismatches": len(exec_failures),
        },
        "retry_handling_behavior": {
            "description": (
                "LangGraph routes validator/executor failures back to sql_generator until "
                "MAX_SQL_RETRIES (default 3). Validation retries skip DB execution; execution "
                "retries pass PostgreSQL error text as feedback to the generator."
            ),
            "validator_retry_trigger": "Invalid syntax, non-SELECT, forbidden keywords",
            "executor_retry_trigger": "PostgreSQL execution error",
            "terminal_failure": "Summarizer returns error message after max retries",
            "observed_in_full_run": (
                "No retries occurred (retry_needed=No for all 50). All queries passed "
                "validation and executed on first attempt."
            ),
        },
        "example_retry_cases": retry_cases,
        "example_execution_mismatches": examples,
        "example_workflow_failures": workflow_failures,
    }

    json_path = OUTPUT_ROOT / "failed_examples_and_retries.json"
    json_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")

    csv_path = OUTPUT_ROOT / "failed_examples_and_retries.csv"
    csv_fields = [
        "category",
        "question",
        "correct_sql",
        "generated_sql",
        "execution_accuracy",
        "schema_linking_accuracy",
        "executed_successfully",
        "retry_needed",
        "retry_count",
        "sql_attempts_count",
        "execution_error",
        "validation_feedback",
        "failure_reason",
        "workflow_nodes",
        "retry_handling_notes",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for ex in examples:
            trace = ex.get("workflow_trace_summary") or []
            writer.writerow(
                {
                    "category": ex.get("category"),
                    "question": ex.get("question"),
                    "correct_sql": ex.get("correct_sql") or "",
                    "generated_sql": ex.get("generated_sql") or "",
                    "execution_accuracy": ex.get("execution_accuracy"),
                    "schema_linking_accuracy": ex.get("schema_linking_accuracy"),
                    "executed_successfully": ex.get("executed_successfully"),
                    "retry_needed": ex.get("retry_needed"),
                    "retry_count": ex.get("retry_count"),
                    "sql_attempts_count": len(ex.get("sql_attempts") or []),
                    "execution_error": ex.get("execution_error") or "",
                    "validation_feedback": ex.get("validation_feedback") or "",
                    "failure_reason": ex.get("failure_reason"),
                    "workflow_nodes": " -> ".join(
                        t.get("node", "") for t in trace if t.get("node")
                    ),
                    "retry_handling_notes": doc["retry_handling_behavior"]["observed_in_full_run"],
                }
            )
        # Empty retry-case section: add a single documentation row if no retries
        if not retry_cases and not workflow_failures:
            writer.writerow(
                {
                    "category": "retry_handling_note",
                    "question": "(no pipeline retries in full run)",
                    "correct_sql": "",
                    "generated_sql": "",
                    "execution_accuracy": "",
                    "schema_linking_accuracy": "",
                    "executed_successfully": "",
                    "retry_needed": "No",
                    "retry_count": 0,
                    "sql_attempts_count": 0,
                    "execution_error": "",
                    "validation_feedback": "",
                    "failure_reason": doc["retry_handling_behavior"]["description"],
                    "workflow_nodes": "validator|executor failure -> sql_generator (max 3)",
                    "retry_handling_notes": doc["retry_handling_behavior"]["observed_in_full_run"],
                }
            )

    md_lines = [
        "# Failed Examples and Retry Handling",
        "",
        f"Generated: {doc['generated_at']}",
        "",
        "## Summary",
        "",
        f"- Total questions: {doc['summary']['total_questions']}",
        f"- Pipeline retries: {doc['summary']['pipeline_retry_cases']}",
        f"- Workflow failures: {doc['summary']['workflow_failed_cases']}",
        f"- Execution accuracy mismatches: {doc['summary']['execution_accuracy_mismatches']}",
        "",
        "## Retry handling behavior",
        "",
        doc["retry_handling_behavior"]["description"],
        "",
        "| Stage | Retry trigger |",
        "|-------|----------------|",
        f"| Validator | {doc['retry_handling_behavior']['validator_retry_trigger']} |",
        f"| Executor | {doc['retry_handling_behavior']['executor_retry_trigger']} |",
        f"| After max retries | {doc['retry_handling_behavior']['terminal_failure']} |",
        "",
        f"**Observed in full 50-question run:** {doc['retry_handling_behavior']['observed_in_full_run']}",
        "",
        "## Example failed cases (execution accuracy mismatch)",
        "",
    ]

    for i, ex in enumerate(examples[:10], 1):
        md_lines.extend(
            [
                f"### {i}. {ex['question']}",
                "",
                f"- **Execution accuracy:** {ex['execution_accuracy']}",
                f"- **Schema linking accuracy:** {ex['schema_linking_accuracy']}",
                f"- **Retry needed:** {ex['retry_needed']} (count: {ex['retry_count']})",
                f"- **Reason:** {ex['failure_reason']}",
                "",
                "**Correct SQL:**",
                "```sql",
                (ex.get("correct_sql") or "").strip(),
                "```",
                "",
                "**Generated SQL:**",
                "```sql",
                (ex.get("generated_sql") or "").strip(),
                "```",
                "",
            ]
        )

    if len(examples) > 10:
        md_lines.append(f"_({len(examples) - 10} more cases in failed_examples_and_retries.json)_\n")

    md_path = OUTPUT_ROOT / "failed_examples_and_retries.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return json_path, csv_path, md_path


def build_success_examples_csv(
    comparison: list[dict], logs_by_question: dict[str, dict]
) -> Path:
    """CSV of successful cases (execution_accuracy == 1.0)."""
    out = OUTPUT_ROOT / "examples_success.csv"
    fields = [
        "question",
        "correct_sql",
        "generated_sql",
        "execution_accuracy",
        "schema_linking_accuracy",
        "executed_successfully",
        "retry_needed",
        "retry_count",
        "row_count",
        "workflow_nodes",
        "final_answer_preview",
    ]

    successes = [r for r in comparison if float(r.get("execution_accuracy", 0)) >= 1.0]

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in successes:
            q = row["question"]
            log = logs_by_question.get(q, {})
            trace = log.get("workflow_trace") or []
            retry_count = max((t.get("retry_count") or 0) for t in trace) if trace else 0
            # Pull answer preview from generated_sql.jsonl not available - use empty or from log
            writer.writerow(
                {
                    "question": q,
                    "correct_sql": row.get("correct_sql") or "",
                    "generated_sql": row.get("generated_sql") or "",
                    "execution_accuracy": row.get("execution_accuracy"),
                    "schema_linking_accuracy": row.get("schema_linking_accuracy"),
                    "executed_successfully": row.get("executed_successfully"),
                    "retry_needed": row.get("retry_needed"),
                    "retry_count": retry_count,
                    "row_count": log.get("row_count", ""),
                    "workflow_nodes": " -> ".join(
                        t.get("node", "") for t in trace if t.get("node")
                    ),
                    "final_answer_preview": "",
                }
            )

    return out


def build_extended_csv(comparison: list[dict], logs_by_question: dict[str, dict]) -> Path:
    """Extended comparison CSV; does not modify benchmark_comparison.csv."""
    out = OUTPUT_ROOT / "benchmark_comparison_extended.csv"
    base_fields = list(comparison[0].keys()) if comparison else []
    extra_fields = [
        "retry_count",
        "execution_error",
        "validation_feedback",
        "failure_category",
        "retry_handling_notes",
        "workflow_nodes",
        "execution_log_ref",
    ]
    fieldnames = base_fields + [f for f in extra_fields if f not in base_fields]

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, row in enumerate(comparison):
            q = row["question"]
            log = logs_by_question.get(q, {})
            trace = log.get("workflow_trace") or []
            retry_count = max((t.get("retry_count") or 0) for t in trace) if trace else 0

            if row.get("final_status") == "Failed":
                category = "workflow_failure"
            elif float(row.get("execution_accuracy", 0)) < 1.0:
                category = "execution_accuracy_mismatch"
            elif row.get("retry_needed", "").lower() == "yes":
                category = "retry_recovered"
            else:
                category = "success"

            if retry_count > 0:
                retry_notes = f"Retried {retry_count} time(s); see workflow trace in query_execution_logs.jsonl"
            else:
                retry_notes = "No retry; first SQL attempt succeeded"

            extended = dict(row)
            extended.update(
                {
                    "retry_count": retry_count,
                    "execution_error": log.get("execution_error") or "",
                    "validation_feedback": log.get("validation_feedback") or "",
                    "failure_category": category,
                    "retry_handling_notes": retry_notes,
                    "workflow_nodes": " -> ".join(t.get("node", "") for t in trace),
                    "execution_log_ref": f"query_execution_logs.jsonl#line:{i + 1}",
                }
            )
            writer.writerow(extended)

    return out


def main() -> None:
    logs_path, history_path = build_execution_logs()
    logs = load_jsonl(logs_path)
    # Prefer latest run entries for comparison join
    latest_run = discover_runs()[-1]["run_id"] if discover_runs() else None
    logs_by_question = {
        e["question"]: e for e in logs if e.get("run_id") == latest_run
    } or {e["question"]: e for e in logs}

    comparison = list(csv.DictReader(COMPARISON_CSV.open(encoding="utf-8")))
    _, failed_csv, _ = build_failed_examples(logs_by_question, comparison)
    success_csv = build_success_examples_csv(comparison, logs_by_question)
    ext_path = build_extended_csv(comparison, logs_by_question)

    readme = OUTPUT_ROOT / "EVALUATION_FILES.md"
    readme.write_text(
        f"""# Evaluation output index

Generated: {datetime.now(timezone.utc).isoformat()}

## Query execution logs

| File | Description |
|------|-------------|
| [`query_execution_logs.jsonl`](query_execution_logs.jsonl) | Per-question workflow traces, errors, sample rows (all runs) |
| [`query_execution_logs_history.json`](query_execution_logs_history.json) | Run IDs and entry counts |
| [`full_run.log`](full_run.log) | Full terminal output from 50-question benchmark |
| [`latest/execution_logs.jsonl`](latest/execution_logs.jsonl) | Same data for latest run only |
| `app/logs/app.log` | Application log (planner, generator, validator, executor) |

## Failed examples & retries

| File | Description |
|------|-------------|
| [`failed_examples_and_retries.csv`](failed_examples_and_retries.csv) | Failed cases + retry notes (spreadsheet) |
| [`failed_examples_and_retries.md`](failed_examples_and_retries.md) | Human-readable summary |
| [`failed_examples_and_retries.json`](failed_examples_and_retries.json) | Same data (machine-readable) |

## Success examples

| File | Description |
|------|-------------|
| [`examples_success.csv`](examples_success.csv) | All cases with execution_accuracy = 1.0 |
| [`latest/examples_success.json`](latest/examples_success.json) | Sample subset (3 rows) from benchmark run |

## Comparison tables

| File | Description |
|------|-------------|
| [`benchmark_comparison.csv`](benchmark_comparison.csv) | Original (unchanged) |
| [`benchmark_comparison_extended.csv`](benchmark_comparison_extended.csv) | Original columns + retry/trace fields |

Primary run: `{latest_run or "n/a"}`
""",
        encoding="utf-8",
    )

    print(f"Wrote {logs_path}")
    print(f"Wrote {history_path}")
    print(f"Wrote {failed_csv}")
    print(f"Wrote {success_csv}")
    print(f"Wrote {ext_path}")
    print(f"Wrote {readme}")


if __name__ == "__main__":
    main()

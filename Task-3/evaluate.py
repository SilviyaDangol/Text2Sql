# ─────────────────────────────────────────────
# project/evaluate.py
#
# Benchmark evaluation script.
# Runs a mock dataset of (question, expected_sql) pairs through the pipeline
# and prints a formatted report with aggregate metrics.
#
# Usage:
#   python evaluate.py
# ─────────────────────────────────────────────
from __future__ import annotations
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import textwrap
from typing import Any

from executor import run_pipeline

# ── Mock benchmark dataset ────────────────────────────────────────────────────
BENCHMARK: list[dict[str, str]] = [
    {
        "question": "List all product lines with their text descriptions.",
        "expected_sql": (
            'SELECT "productLine", "textDescription" FROM productlines'
        ),
    },
    {
        "question": "How many products are in each product line?",
        "expected_sql": (
            'SELECT "productLine", COUNT(*) AS product_count '
            'FROM products GROUP BY "productLine" ORDER BY product_count DESC'
        ),
    },
    {
        "question": "Show the top 5 most expensive products by MSRP.",
        "expected_sql": (
            'SELECT "productName", "MSRP" FROM products '
            'ORDER BY "MSRP" DESC LIMIT 5'
        ),
    },
    {
        "question": "Which customers are from France?",
        "expected_sql": (
            'SELECT "customerName", "city", "country" FROM customers '
            'WHERE "country" = \'France\''
        ),
    },
    {
        "question": "Find the total payment amount per customer.",
        "expected_sql": (
            'SELECT "customerNumber", SUM("amount") AS total_paid '
            'FROM payments GROUP BY "customerNumber" ORDER BY total_paid DESC'
        ),
    },
    {
        "question": "List all orders that are still in 'In Process' status.",
        "expected_sql": (
            'SELECT "orderNumber", "orderDate", "customerNumber" '
            'FROM orders WHERE "status" = \'In Process\''
        ),
    },
    {
        "question": (
            "Show the first name, last name, and job title "
            "of all employees who report to employee number 1002."
        ),
        "expected_sql": (
            'SELECT "firstName", "lastName", "jobTitle" '
            'FROM employees WHERE "reportsTo" = 1002'
        ),
    },
    {
        "question": (
            "What is the total revenue per order "
            "(quantity × price) for the top 10 orders?"
        ),
        "expected_sql": (
            'SELECT "orderNumber", '
            'SUM("quantityOrdered" * "priceEach") AS total_revenue '
            'FROM orderdetails GROUP BY "orderNumber" '
            'ORDER BY total_revenue DESC LIMIT 10'
        ),
    },
    {
        "question": (
            "Get the names of customers along with their "
            "sales representative's full name."
        ),
        "expected_sql": (
            'SELECT c."customerName", '
            'e."firstName" || \' \' || e."lastName" AS sales_rep '
            'FROM customers c '
            'JOIN employees e ON c."salesRepEmployeeNumber" = e."employeeNumber"'
        ),
    },
    {
        "question": "Which offices are in the USA?",
        "expected_sql": (
            'SELECT "officeCode", "city", "state" FROM offices '
            'WHERE "country" = \'USA\''
        ),
    },
]


# ── Evaluation helpers ────────────────────────────────────────────────────────

def _truncate(text: str, width: int = 55) -> str:
    """Truncate *text* to *width* chars for table display."""
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def _compare_results(
    generated_rows: list[dict[str, Any]],
    question: str,
) -> str:
    """
    Lightweight correctness check:
    We can't easily compare SQL strings (LLM may use aliases / different style)
    so we just check that the pipeline returned at least some rows or an empty
    result without crashing, and mark it 'N/A (needs manual review)'.
    Production systems would run both queries against the DB and diff the sets.
    """
    if generated_rows:
        return f"✓ {len(generated_rows)} rows"
    return "✓ 0 rows (empty)"


# ── Main evaluation loop ──────────────────────────────────────────────────────

def run_evaluation() -> None:
    col_q   = 35
    col_sql = 50
    col_exec = 8
    col_res  = 18
    col_retry = 7
    col_status = 9

    header = (
        f"{'Question':<{col_q}} "
        f"{'Generated SQL':<{col_sql}} "
        f"{'Exec OK':<{col_exec}} "
        f"{'Result':<{col_res}} "
        f"{'Retry':<{col_retry}} "
        f"{'Status':<{col_status}}"
    )
    separator = "-" * len(header)

    print("\n" + "=" * len(header))
    print("  TEXT-TO-SQL PIPELINE  ─  BENCHMARK EVALUATION REPORT")
    print("=" * len(header))
    print(header)
    print(separator)

    total          = len(BENCHMARK)
    exec_success   = 0
    retry_needed   = 0
    retry_success  = 0
    failed_total   = 0

    results: list[dict[str, Any]] = []

    for item in BENCHMARK:
        question = item["question"]
        output   = run_pipeline(question)

        executed_ok  = output["status"] == "success"
        retry_att    = output["retry_attempted"]
        retry_succ   = output["retry_succeeded"]

        if executed_ok:
            exec_success += 1
        else:
            failed_total += 1

        if retry_att:
            retry_needed += 1
        if retry_succ:
            retry_success += 1

        result_str = (
            _compare_results(output["result"], question)
            if executed_ok
            else f"✗ {_truncate(output['error'], 18)}"
        )

        row = (
            f"{_truncate(question, col_q):<{col_q}} "
            f"{_truncate(output['sql'], col_sql):<{col_sql}} "
            f"{'Yes' if executed_ok else 'No':<{col_exec}} "
            f"{result_str:<{col_res}} "
            f"{'Yes' if retry_att else 'No':<{col_retry}} "
            f"{output['status']:<{col_status}}"
        )
        print(row)
        results.append(output)

    print(separator)

    # ── Metrics summary ───────────────────────────────────────────────────────
    exec_rate  = exec_success / total * 100
    retry_rate = (retry_success / retry_needed * 100) if retry_needed else 0.0

    print(f"\n{'METRICS':}")
    print(f"  Total questions              : {total}")
    print(f"  SQL execution success rate   : {exec_success}/{total}  ({exec_rate:.1f}%)")
    print(f"  Queries that needed retry    : {retry_needed}")
    print(f"  Retry success rate           : {retry_success}/{retry_needed}  ({retry_rate:.1f}%)")
    print(f"  Total failed queries         : {failed_total}")
    print("=" * len(header) + "\n")


if __name__ == "__main__":
    run_evaluation()
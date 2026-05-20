"""
SQL Query Decomposer
--------------------
Reads natural language SQL questions from a CSV file, decomposes each
into structured components using OpenAI, and saves results to a CSV file.

Usage:
    python query_decomposer.py
    python query_decomposer.py --input questions.csv --output results.csv
    python query_decomposer.py --question "Your question here"
    python query_decomposer.py --interactive
"""

import os
import json
import time
import argparse
import csv
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_INPUT_CSV  = "data/sql_questions_only - sql_questions_only.csv"
DEFAULT_OUTPUT_CSV = "data/decomposed_questions.csv"

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are an expert SQL analyst. Your job is to decompose natural language questions
into structured SQL query components to help users understand how to build SQL queries.

For each question, identify and return ONLY a JSON object with these exact keys:
{
  "intent":   "What the query is trying to achieve (e.g., Count, List, Find, Calculate)",
  "tables":   ["list", "of", "tables"],
  "columns":  ["list", "of", "columns"],
  "filters":  ["list of WHERE conditions, or empty list if none"],
  "joins":    ["list of JOIN conditions, or empty list if none"],
  "group_by": ["list of GROUP BY columns, or empty list if none"],
  "order_by": ["list of ORDER BY columns, or empty list if none"],
  "notes":    "Any extra clarifications or assumptions made"
}

Rules:
- Return ONLY valid JSON. No markdown, no extra text, no code fences.
- Use snake_case for table/column names if names are inferred.
- If the question is ambiguous, make reasonable assumptions and note them in "notes".
- Be specific and concise in each field.
- For list fields with no values, return an empty list [].
""".strip()


=
def decompose_query(question: str) -> dict:
    """Send a question to OpenAI and return structured decomposition as dict."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Decompose this question:\n\n{question}"},
        ],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end:
            return json.loads(raw[start:end])
        raise ValueError(f"Could not parse JSON from model response:\n{raw}")


# ── CSV I/O helpers ───────────────────────────────────────────────────────────

def read_questions_csv(filepath: str) -> list:
    """Read questions from a CSV file. Accepts 'question' column or first column."""
    questions = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        col = "question" if "question" in (reader.fieldnames or []) else reader.fieldnames[0]
        for row in reader:
            q = row[col].strip()
            if q:
                questions.append(q)
    return questions


def write_results_csv(results: list, filepath: str) -> None:
    """
    Write decomposition results to CSV.
    Each row has: question + all decomposition fields.
    List fields are stored as JSON strings so the CSV stays flat.
    """
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "question",
        "intent",
        "tables",
        "columns",
        "filters",
        "joins",
        "group_by",
        "order_by",
        "notes",
        "raw_json",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            decomp = r["decomposition"]
            writer.writerow({
                "question": r["question"],
                "intent":   decomp.get("intent", ""),
                "tables":   json.dumps(decomp.get("tables",   [])),
                "columns":  json.dumps(decomp.get("columns",  [])),
                "filters":  json.dumps(decomp.get("filters",  [])),
                "joins":    json.dumps(decomp.get("joins",    [])),
                "group_by": json.dumps(decomp.get("group_by", [])),
                "order_by": json.dumps(decomp.get("order_by", [])),
                "notes":    decomp.get("notes", ""),
                "raw_json": json.dumps(decomp),
            })


# ── Pretty-print helper ───────────────────────────────────────────────────────

def fmt_list(lst) -> str:
    if not lst:
        return "None"
    return ", ".join(lst) if isinstance(lst, list) else str(lst)


def print_decomposition(question: str, result: dict) -> None:
    divider = "─" * 60
    print(f"\n{divider}")
    print(f"  QUESTION : {question}")
    print(divider)
    print(f"  Intent   : {result.get('intent', 'N/A')}")
    print(f"  Tables   : {fmt_list(result.get('tables'))}")
    print(f"  Columns  : {fmt_list(result.get('columns'))}")
    print(f"  Filters  : {fmt_list(result.get('filters'))}")
    print(f"  Joins    : {fmt_list(result.get('joins'))}")
    print(f"  Group By : {fmt_list(result.get('group_by'))}")
    print(f"  Order By : {fmt_list(result.get('order_by'))}")
    if result.get("notes"):
        print(f"  Notes    : {result['notes']}")
    print(divider)


# ── Batch processor ───────────────────────────────────────────────────────────

def process_csv(input_path: str, output_path: str) -> None:
    """Read questions from CSV, decompose each, save results to output CSV."""
    if not Path(input_path).exists():
        print(f"ERROR: Input file not found: {input_path}")
        return

    questions = read_questions_csv(input_path)
    total     = len(questions)
    print(f"\n Found {total} questions in '{input_path}'. Processing...\n")

    results = []

    for i, question in enumerate(questions, 1):
        print(f"  [{i}/{total}] {question[:70]}{'...' if len(question) > 70 else ''}")
        try:
            decomp = decompose_query(question)
            print_decomposition(question, decomp)
            results.append({"question": question, "decomposition": decomp})
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({
                "question": question,
                "decomposition": {
                    "intent": "ERROR", "tables": [], "columns": [],
                    "filters": [], "joins": [], "group_by": [], "order_by": [],
                    "notes": str(e),
                },
            })

        # Small delay to avoid rate-limit bursts
        if i < total:
            time.sleep(0.3)

    write_results_csv(results, output_path)
    print(f"\n✅  Done! Results saved to '{output_path}' ({len(results)} rows)\n")


# ── Main entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Decompose SQL questions from a CSV using OpenAI."
    )
    parser.add_argument("--input",  "-i", default=DEFAULT_INPUT_CSV,
                        help=f"Input CSV file (default: {DEFAULT_INPUT_CSV})")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT_CSV,
                        help=f"Output CSV file (default: {DEFAULT_OUTPUT_CSV})")
    parser.add_argument("--question", "-q", type=str,
                        help="Decompose a single question (skips CSV).")
    parser.add_argument("--interactive", action="store_true",
                        help="Interactive REPL mode.")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not found. Add it to your .env file.")
        return

    # ── Single question mode ──
    if args.question:
        result = decompose_query(args.question)
        print_decomposition(args.question, result)
        print("\nJSON:\n" + json.dumps(result, indent=2))
        return

    # ── Interactive mode ──
    if args.interactive:
        print("\n SQL Query Decomposer — Interactive Mode")
        print("  Type 'exit' to quit.\n")
        while True:
            question = input("Your question: ").strip()
            if question.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            if not question:
                continue
            result = decompose_query(question)
            print_decomposition(question, result)
            print("\nJSON:\n" + json.dumps(result, indent=2))
        return

    # ── Default: batch CSV mode ──
    process_csv(args.input, args.output)


if __name__ == "__main__":
    main()
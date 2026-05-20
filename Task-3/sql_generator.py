# ─────────────────────────────────────────────
# project/sql_generator.py
#
# Handles ALL three LLM calls in the pipeline:
#   1. decompose()  – NL → structured JSON
#   2. generate()   – JSON + schema → SQL
#   3. fix()        – SQL + error → corrected SQL
#
# All prompt templates are defined inline in this file to avoid any
# cross-package import issues regardless of working directory or how
# Streamlit launches the app.
# ─────────────────────────────────────────────
from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# PROMPT TEMPLATES  (inlined — no package import needed)
# ══════════════════════════════════════════════════════════════════════════════

DB_SCHEMA = """
-- classicmodels schema (PostgreSQL)
-- NOTE: all identifiers use double-quoted camelCase

CREATE TABLE productlines (
  "productLine"      VARCHAR(50)   PRIMARY KEY,
  "textDescription"  VARCHAR(4000),
  "htmlDescription"  TEXT,
  "image"            BYTEA
);

CREATE TABLE products (
  "productCode"        VARCHAR(15)    PRIMARY KEY,
  "productName"        VARCHAR(70)    NOT NULL,
  "productLine"        VARCHAR(50)    NOT NULL,
  "productScale"       VARCHAR(10)    NOT NULL,
  "productVendor"      VARCHAR(50)    NOT NULL,
  "productDescription" TEXT           NOT NULL,
  "quantityInStock"    INTEGER        NOT NULL,
  "buyPrice"           NUMERIC(10,2)  NOT NULL,
  "MSRP"               NUMERIC(10,2)  NOT NULL,
  FOREIGN KEY ("productLine") REFERENCES productlines("productLine")
);

CREATE TABLE offices (
  "officeCode"   VARCHAR(10) PRIMARY KEY,
  "city"         VARCHAR(50) NOT NULL,
  "phone"        VARCHAR(50) NOT NULL,
  "addressLine1" VARCHAR(50) NOT NULL,
  "addressLine2" VARCHAR(50),
  "state"        VARCHAR(50),
  "country"      VARCHAR(50) NOT NULL,
  "postalCode"   VARCHAR(15) NOT NULL,
  "territory"    VARCHAR(10) NOT NULL
);

CREATE TABLE employees (
  "employeeNumber" INTEGER      PRIMARY KEY,
  "lastName"       VARCHAR(50)  NOT NULL,
  "firstName"      VARCHAR(50)  NOT NULL,
  "extension"      VARCHAR(10)  NOT NULL,
  "email"          VARCHAR(100) NOT NULL,
  "officeCode"     VARCHAR(10)  NOT NULL,
  "reportsTo"      INTEGER,
  "jobTitle"       VARCHAR(50)  NOT NULL,
  FOREIGN KEY ("reportsTo") REFERENCES employees("employeeNumber"),
  FOREIGN KEY ("officeCode") REFERENCES offices("officeCode")
);

CREATE TABLE customers (
  "customerNumber"         INTEGER        PRIMARY KEY,
  "customerName"           VARCHAR(50)    NOT NULL,
  "contactLastName"        VARCHAR(50)    NOT NULL,
  "contactFirstName"       VARCHAR(50)    NOT NULL,
  "phone"                  VARCHAR(50)    NOT NULL,
  "addressLine1"           VARCHAR(50)    NOT NULL,
  "addressLine2"           VARCHAR(50),
  "city"                   VARCHAR(50)    NOT NULL,
  "state"                  VARCHAR(50),
  "postalCode"             VARCHAR(15),
  "country"                VARCHAR(50)    NOT NULL,
  "salesRepEmployeeNumber" INTEGER,
  "creditLimit"            NUMERIC(10,2),
  FOREIGN KEY ("salesRepEmployeeNumber") REFERENCES employees("employeeNumber")
);

CREATE TABLE payments (
  "customerNumber" INTEGER       NOT NULL,
  "checkNumber"    VARCHAR(50)   NOT NULL,
  "paymentDate"    DATE          NOT NULL,
  "amount"         NUMERIC(10,2) NOT NULL,
  PRIMARY KEY ("customerNumber", "checkNumber"),
  FOREIGN KEY ("customerNumber") REFERENCES customers("customerNumber")
);

CREATE TABLE orders (
  "orderNumber"    INTEGER     PRIMARY KEY,
  "orderDate"      DATE        NOT NULL,
  "requiredDate"   DATE        NOT NULL,
  "shippedDate"    DATE,
  "status"         VARCHAR(15) NOT NULL,
  "comments"       TEXT,
  "customerNumber" INTEGER     NOT NULL,
  FOREIGN KEY ("customerNumber") REFERENCES customers("customerNumber")
);

CREATE TABLE orderdetails (
  "orderNumber"     INTEGER       NOT NULL,
  "productCode"     VARCHAR(15)   NOT NULL,
  "quantityOrdered" INTEGER       NOT NULL,
  "priceEach"       NUMERIC(10,2) NOT NULL,
  "orderLineNumber" SMALLINT      NOT NULL,
  PRIMARY KEY ("orderNumber", "productCode"),
  FOREIGN KEY ("orderNumber") REFERENCES orders("orderNumber"),
  FOREIGN KEY ("productCode") REFERENCES products("productCode")
);
"""

# ── Step 1 – Decomposition ────────────────────────────────────────────────────
DECOMPOSE_SYSTEM = """\
You are a SQL analyst. Your job is to decompose a natural-language question
about a relational database into a structured JSON object.

Return ONLY valid JSON — no markdown fences, no extra text.

The JSON must have exactly these keys:
  "intent"  : one-sentence description of what the query should do
  "tables"  : list of table names required
  "columns" : list of column names required (use "table.column" format)
  "filters" : list of WHERE-clause conditions in plain English
  "joins"   : list of JOIN relationships needed (e.g. "orders JOIN customers ON ...")
"""

DECOMPOSE_USER = """\
Question: {question}

Respond with only the JSON object described in the system prompt.
"""

# ── Step 2 – SQL Generation ───────────────────────────────────────────────────
GENERATE_SYSTEM = """\
You are an expert PostgreSQL query writer.

Given a structured decomposition of a user question and the full database
schema below, write a single, correct PostgreSQL SELECT query.

Rules:
- Output ONLY the raw SQL query — no markdown, no explanation, no backticks.
- Use double-quoted identifiers exactly as they appear in the schema
  (e.g. "customerName", "orderNumber").
- Only use SELECT statements. Never use INSERT, UPDATE, DELETE, DROP, ALTER,
  or TRUNCATE.
- Alias columns when helpful for readability.
- Use explicit JOIN ... ON syntax.
- If aggregation is required use GROUP BY appropriately.

Database schema:
{schema}
"""

GENERATE_USER = """\
Decomposed question:
{decomposition}

Write the PostgreSQL SELECT query now.
"""

# ── Step 3 – Self-correction / Fix ───────────────────────────────────────────
FIX_SYSTEM = """\
You are an expert PostgreSQL debugger.

You will receive a SQL query that was executed against a PostgreSQL database
and the exact error message it produced. Fix the query so it executes without
errors.

Rules:
- Output ONLY the corrected raw SQL query — no markdown, no explanation, no
  backticks.
- Preserve the original intent of the query.
- Use double-quoted identifiers exactly as they appear in the schema.
- Only return SELECT statements.

Database schema:
{schema}
"""

FIX_USER = """\
Original SQL:
{sql}

Database error:
{error}

Return the corrected SQL query.
"""

# ══════════════════════════════════════════════════════════════════════════════
# OpenAI client (singleton)
# ══════════════════════════════════════════════════════════════════════════════

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set. "
                "Add it to your .env file or environment."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def _chat(system: str, user: str, temperature: float = 0.0) -> str:
    """Single chat-completion call. Returns the assistant message content."""
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = _get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=temperature,
        max_tokens=1024,
    )
    return response.choices[0].message.content.strip()


# ══════════════════════════════════════════════════════════════════════════════
# LLM Call 1 – Decomposition
# ══════════════════════════════════════════════════════════════════════════════

def decompose(question: str) -> dict[str, Any]:
    """Decompose a natural-language question into a structured JSON object.

    Returns dict with keys: intent, tables, columns, filters, joins
    """
    raw = _chat(
        system=DECOMPOSE_SYSTEM,
        user=DECOMPOSE_USER.format(question=question),
    )

    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    try:
        result: dict[str, Any] = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Decomposition LLM did not return valid JSON.\n"
            f"Raw response: {raw}\nError: {exc}"
        ) from exc

    for key in ("intent", "tables", "columns", "filters", "joins"):
        result.setdefault(key, [] if key != "intent" else "")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# LLM Call 2 – SQL Generation
# ══════════════════════════════════════════════════════════════════════════════

def generate_sql(decomposition: dict[str, Any]) -> str:
    """Generate a PostgreSQL SELECT query from the decomposed question."""
    decomp_str = json.dumps(decomposition, indent=2)
    raw = _chat(
        system=GENERATE_SYSTEM.format(schema=DB_SCHEMA),
        user=GENERATE_USER.format(decomposition=decomp_str),
    )
    return _strip_sql_fences(raw)


# ══════════════════════════════════════════════════════════════════════════════
# LLM Call 3 – Self-Correction / Fix
# ══════════════════════════════════════════════════════════════════════════════

def fix_sql(sql: str, error: str) -> str:
    """Ask the LLM to fix a SQL query that produced a database error."""
    raw = _chat(
        system=FIX_SYSTEM.format(schema=DB_SCHEMA),
        user=FIX_USER.format(sql=sql, error=error),
    )
    return _strip_sql_fences(raw)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _strip_sql_fences(text: str) -> str:
    """Remove markdown code fences and surrounding whitespace."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = [
            line for line in lines[1:]
            if not line.strip().startswith("```")
        ]
        text = "\n".join(inner).strip()
    return text
"""Execution accuracy and schema linking metrics for Text-to-SQL evaluation."""

from __future__ import annotations

import re
from typing import Any

import sqlparse
from sqlparse.sql import Identifier, IdentifierList
from sqlparse.tokens import Keyword

# ClassicModels public schema (lowercase table names in PostgreSQL)
SCHEMA_TABLES = {
    "productlines",
    "products",
    "offices",
    "employees",
    "customers",
    "payments",
    "orders",
    "orderdetails",
}

SCHEMA_COLUMNS = {
    "productLine",
    "textDescription",
    "htmlDescription",
    "image",
    "productCode",
    "productName",
    "productScale",
    "productVendor",
    "productDescription",
    "quantityInStock",
    "buyPrice",
    "MSRP",
    "officeCode",
    "city",
    "phone",
    "addressLine1",
    "addressLine2",
    "state",
    "country",
    "postalCode",
    "territory",
    "employeeNumber",
    "lastName",
    "firstName",
    "extension",
    "email",
    "reportsTo",
    "jobTitle",
    "customerNumber",
    "customerName",
    "contactLastName",
    "contactFirstName",
    "salesRepEmployeeNumber",
    "creditLimit",
    "checkNumber",
    "paymentDate",
    "amount",
    "orderNumber",
    "orderDate",
    "requiredDate",
    "shippedDate",
    "status",
    "comments",
    "quantityOrdered",
    "priceEach",
    "orderLineNumber",
}


def _normalize_sql(sql: str) -> str:
    return " ".join((sql or "").split()).strip().rstrip(";").lower()


def extract_tables(sql: str) -> set[str]:
    """Extract referenced table names from SQL."""
    if not sql or not sql.strip():
        return set()

    found: set[str] = set()
    parsed = sqlparse.parse(sql)
    if not parsed:
        return found

    for statement in parsed:
        from_seen = False
        for token in statement.tokens:
            if from_seen:
                if isinstance(token, IdentifierList):
                    for ident in token.get_identifiers():
                        name = ident.get_real_name()
                        if name:
                            found.add(name.lower())
                elif isinstance(token, Identifier):
                    name = token.get_real_name()
                    if name:
                        found.add(name.lower())
                elif token.ttype is Keyword and token.value.upper() in (
                    "WHERE",
                    "GROUP",
                    "ORDER",
                    "HAVING",
                    "LIMIT",
                    "JOIN",
                    "INNER",
                    "LEFT",
                    "RIGHT",
                    "FULL",
                    "CROSS",
                    "ON",
                ):
                    if token.value.upper() in ("JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS"):
                        continue
                    if token.value.upper() not in ("JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS"):
                        from_seen = False
            if token.ttype is Keyword and token.value.upper() == "FROM":
                from_seen = True
            if token.ttype is Keyword and token.value.upper() in (
                "JOIN",
                "INNER JOIN",
                "LEFT JOIN",
                "RIGHT JOIN",
            ):
                from_seen = True

    # Fallback regex for aliases: FROM/JOIN table [alias]
    for match in re.finditer(
        r"(?:FROM|JOIN)\s+([a-zA-Z_][\w]*)\b",
        sql,
        re.IGNORECASE,
    ):
        t = match.group(1).lower()
        if t in SCHEMA_TABLES:
            found.add(t)

    return found & SCHEMA_TABLES


def extract_columns(sql: str) -> set[str]:
    """Extract column identifiers (quoted or known schema columns)."""
    if not sql or not sql.strip():
        return set()

    found: set[str] = set()
    for match in re.finditer(r'"([a-zA-Z][\w]*)"', sql):
        col = match.group(1)
        if col in SCHEMA_COLUMNS:
            found.add(col)

    upper = sql.upper()
    for col in SCHEMA_COLUMNS:
        if f'"{col}"'.upper() in upper or f".{col}".upper() in upper:
            found.add(col)

    return found


def _f1(predicted: set[str], gold: set[str]) -> float:
    if not gold and not predicted:
        return 1.0
    if not gold or not predicted:
        return 0.0
    tp = len(predicted & gold)
    precision = tp / len(predicted)
    recall = tp / len(gold)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def schema_linking_accuracy(reference_sql: str, generated_sql: str) -> float:
    """
    B. Schema linking accuracy: F1 over tables and columns vs reference SQL.
    """
    ref_tables = extract_tables(reference_sql)
    gen_tables = extract_tables(generated_sql)
    ref_cols = extract_columns(reference_sql)
    gen_cols = extract_columns(generated_sql)

    table_f1 = _f1(gen_tables, ref_tables)
    col_f1 = _f1(gen_cols, ref_cols)
    return round((table_f1 + col_f1) / 2, 4)


def _row_signature(row: dict[str, Any]) -> tuple[str, ...]:
    """Order-insensitive row signature for result comparison."""
    return tuple(sorted(str(v) for v in row.values()))


def _normalize_rows(rows: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    return sorted(_row_signature(r) for r in rows)


def result_sets_match(
    reference_rows: list[dict[str, Any]],
    generated_rows: list[dict[str, Any]],
) -> bool:
    """Compare query results (order-insensitive, column-name tolerant)."""
    if len(reference_rows) != len(generated_rows):
        return False
    return _normalize_rows(reference_rows) == _normalize_rows(generated_rows)


def execution_accuracy(
    reference_result: dict[str, Any],
    generated_result: dict[str, Any],
) -> float:
    """
    B. Execution accuracy: 1.0 if both execute and result sets match, else 0.0.
    """
    if not reference_result.get("success") or not generated_result.get("success"):
        return 0.0
    ref_rows = reference_result.get("rows") or []
    gen_rows = generated_result.get("rows") or []
    return 1.0 if result_sets_match(ref_rows, gen_rows) else 0.0

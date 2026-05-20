"""Database connection utilities and safe read-only query execution."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import logger, settings
from app.db import get_engine

FORBIDDEN_KEYWORDS = (
    "DROP",
    "DELETE",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "MERGE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "CALL",
)


def _json_serialize(value: Any) -> Any:
    """Convert database values to JSON-serializable types."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return "<binary>"
    return value


def fetch_schema_summary() -> str:
    """Return a concise schema summary for LLM context."""
    logger.info("Fetching schema summary from information_schema")
    query = text(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
    )
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(query).mappings().all()
        if not rows:
            logger.warning("No schema rows found; using static fallback")
            return _static_schema_summary()

        lines: list[str] = []
        current_table = ""
        for row in rows:
            table = row["table_name"]
            if table != current_table:
                current_table = table
                lines.append(f"\n{table}:")
            lines.append(f"  - {row['column_name']} ({row['data_type']})")
        summary = "\n".join(lines)
        logger.info("Schema summary fetched | tables=%d", len({r["table_name"] for r in rows}))
        return summary
    except SQLAlchemyError as exc:
        logger.error("Failed to fetch schema summary: %s", exc)
        return _static_schema_summary()


def _static_schema_summary() -> str:
    """Static schema fallback when DB metadata is unavailable."""
    return """
productlines(productLine PK, textDescription, htmlDescription, image)
products(productCode PK, productName, productLine FK, productScale, productVendor, productDescription, quantityInStock, buyPrice, MSRP)
offices(officeCode PK, city, phone, addressLine1, addressLine2, state, country, postalCode, territory)
employees(employeeNumber PK, lastName, firstName, extension, email, officeCode FK, reportsTo FK, jobTitle)
customers(customerNumber PK, customerName, contactLastName, contactFirstName, phone, addressLine1, addressLine2, city, state, postalCode, country, salesRepEmployeeNumber FK, creditLimit)
payments(customerNumber PK/FK, checkNumber PK, paymentDate, amount)
orders(orderNumber PK, orderDate, requiredDate, shippedDate, status, comments, customerNumber FK)
orderdetails(orderNumber PK/FK, productCode PK/FK, quantityOrdered, priceEach, orderLineNumber)
""".strip()


def is_read_only_sql(sql: str) -> tuple[bool, str | None]:
    """Reject destructive or multi-statement SQL."""
    normalized = sql.strip().rstrip(";")
    upper = normalized.upper()

    if ";" in normalized:
        return False, "Multiple SQL statements are not allowed."

    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in upper.split():
            return False, f"Forbidden keyword detected: {keyword}"

    if not upper.startswith("SELECT") and not upper.startswith("WITH"):
        return False, "Only SELECT (or WITH ... SELECT) queries are permitted."

    return True, None


def execute_read_query(sql: str) -> dict[str, Any]:
    """
    Execute a validated read-only SQL query and return JSON-friendly results.

    Returns dict with keys: success, rows, row_count, columns, error.
    """
    logger.info("Executing read query")
    ok, reason = is_read_only_sql(sql)
    if not ok:
        logger.warning("Query rejected before execution: %s", reason)
        return {"success": False, "rows": [], "row_count": 0, "columns": [], "error": reason}

    limited_sql = sql.strip().rstrip(";")
    if "LIMIT" not in limited_sql.upper():
        limited_sql = f"{limited_sql} LIMIT {settings.sql_row_limit}"

    try:
        with get_engine().connect() as conn:
            result = conn.execute(text(limited_sql))
            columns = list(result.keys())
            raw_rows = result.mappings().all()
            rows = [
                {k: _json_serialize(v) for k, v in dict(row).items()}
                for row in raw_rows
            ]
        payload = {
            "success": True,
            "rows": rows,
            "row_count": len(rows),
            "columns": columns,
            "error": None,
        }
        logger.info("Query executed successfully | row_count=%d", len(rows))
        return payload
    except SQLAlchemyError as exc:
        logger.error("Query execution failed: %s", exc)
        return {
            "success": False,
            "rows": [],
            "row_count": 0,
            "columns": [],
            "error": str(exc),
        }


def results_to_json_string(results: dict[str, Any]) -> str:
    """Serialize execution results for LLM consumption."""
    return json.dumps(results, indent=2, default=str)

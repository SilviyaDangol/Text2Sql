# ─────────────────────────────────────────────
# project/validator.py
#
# Rule-based SQL security validation.
# Blocks any DML / DDL that could mutate or destroy data.
# ─────────────────────────────────────────────
from __future__ import annotations
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import re

# Keywords whose presence in a query is always forbidden
_FORBIDDEN: tuple[str, ...] = (
    "DELETE",
    "DROP",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "EXECUTE",
    "EXEC",
    "CALL",
    "CREATE",
    "REPLACE",
    "MERGE",
)

# Build a single compiled regex for speed (word-boundary aware, case-insensitive)
_FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(_FORBIDDEN) + r")\b",
    re.IGNORECASE,
)

# The query must start with SELECT (after stripping whitespace / comments)
_SELECT_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


class ValidationError(ValueError):
    """Raised when a SQL query fails the security check."""


def validate_sql(sql: str) -> str:
    """Validate that *sql* is a safe, read-only SELECT statement.

    Parameters
    ----------
    sql : str
        Raw SQL string from the LLM.

    Returns
    -------
    str
        The original sql string (unchanged) if it passes validation.

    Raises
    ------
    ValidationError
        If the query contains forbidden keywords or does not start with SELECT.
    """
    if not sql or not sql.strip():
        raise ValidationError("SQL query is empty.")

    # 1. Must start with SELECT
    if not _SELECT_RE.match(sql):
        raise ValidationError(
            "Query must start with SELECT. "
            f"Received: {sql[:80]!r}"
        )

    # 2. Must not contain any forbidden keyword
    match = _FORBIDDEN_RE.search(sql)
    if match:
        raise ValidationError(
            f"Forbidden SQL keyword detected: '{match.group().upper()}'. "
            "Only read-only SELECT queries are permitted."
        )

    return sql
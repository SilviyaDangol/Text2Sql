# ─────────────────────────────────────────────
# project/prompts/templates.py
#
# All LLM prompt templates used by the pipeline.
# Each template is a plain string with {placeholders} for .format() calls.
# ─────────────────────────────────────────────

# ── Database schema handed to the generation prompt ──────────────────────────
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
  "employeeNumber" INTEGER     PRIMARY KEY,
  "lastName"       VARCHAR(50) NOT NULL,
  "firstName"      VARCHAR(50) NOT NULL,
  "extension"      VARCHAR(10) NOT NULL,
  "email"          VARCHAR(100) NOT NULL,
  "officeCode"     VARCHAR(10) NOT NULL,
  "reportsTo"      INTEGER,
  "jobTitle"       VARCHAR(50) NOT NULL,
  FOREIGN KEY ("reportsTo") REFERENCES employees("employeeNumber"),
  FOREIGN KEY ("officeCode") REFERENCES offices("officeCode")
);

CREATE TABLE customers (
  "customerNumber"          INTEGER        PRIMARY KEY,
  "customerName"            VARCHAR(50)    NOT NULL,
  "contactLastName"         VARCHAR(50)    NOT NULL,
  "contactFirstName"        VARCHAR(50)    NOT NULL,
  "phone"                   VARCHAR(50)    NOT NULL,
  "addressLine1"            VARCHAR(50)    NOT NULL,
  "addressLine2"            VARCHAR(50),
  "city"                    VARCHAR(50)    NOT NULL,
  "state"                   VARCHAR(50),
  "postalCode"              VARCHAR(15),
  "country"                 VARCHAR(50)    NOT NULL,
  "salesRepEmployeeNumber"  INTEGER,
  "creditLimit"             NUMERIC(10,2),
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
  FOREIGN KEY ("orderNumber")  REFERENCES orders("orderNumber"),
  FOREIGN KEY ("productCode")  REFERENCES products("productCode")
);
"""


# ── STEP 1 – Decomposition prompt ────────────────────────────────────────────
DECOMPOSE_SYSTEM = """\
You are a SQL analyst. Your job is to decompose a natural-language question
about a relational database into a structured JSON object.

Return ONLY valid JSON — no markdown fences, no extra text.

The JSON must have exactly these keys:
  "intent"   : one-sentence description of what the query should do
  "tables"   : list of table names required
  "columns"  : list of column names required (use "table.column" format)
  "filters"  : list of WHERE-clause conditions in plain English
  "joins"    : list of JOIN relationships needed (e.g. "orders JOIN customers ON …")
"""

DECOMPOSE_USER = """\
Question: {question}

Respond with only the JSON object described in the system prompt.
"""


# ── STEP 2 – SQL Generation prompt ───────────────────────────────────────────
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
- Use explicit JOIN … ON syntax.
- If aggregation is required use GROUP BY appropriately.

Database schema:
{schema}
"""

GENERATE_USER = """\
Decomposed question:
{decomposition}

Write the PostgreSQL SELECT query now.
"""


# ── STEP 3 – Self-correction / Fix prompt ────────────────────────────────────
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

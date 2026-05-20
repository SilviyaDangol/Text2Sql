# ─────────────────────────────────────────────
# project/streamlit_app.py
#
# Streamlit Chat UI for the Text-to-SQL pipeline.
# ─────────────────────────────────────────────
from __future__ import annotations
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))



import pandas as pd
import streamlit as st

from database import test_connection
from executor import run_pipeline
from logger import read_logs

# ── Page configuration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Text-to-SQL · ClassicModels",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

        html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }

        section[data-testid="stSidebar"] {
            background: #0f1117;
            border-right: 1px solid #2a2d3a;
        }
        .user-bubble {
            background: #1e293b;
            border-left: 3px solid #6366f1;
            border-radius: 0 8px 8px 0;
            padding: 0.75rem 1rem;
            margin: 0.5rem 0;
            font-size: 0.95rem;
        }
        .assistant-bubble {
            background: #0f1117;
            border-left: 3px solid #10b981;
            border-radius: 0 8px 8px 0;
            padding: 0.75rem 1rem;
            margin: 0.5rem 0;
        }
        .sql-block {
            background: #111827;
            border: 1px solid #374151;
            border-radius: 6px;
            padding: 1rem;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.82rem;
            white-space: pre-wrap;
            word-break: break-all;
            color: #a5f3fc;
            margin: 0.5rem 0 1rem 0;
        }
        .badge-success {
            background: #064e3b; color: #6ee7b7;
            padding: 2px 10px; border-radius: 999px;
            font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em;
        }
        .badge-failed {
            background: #450a0a; color: #fca5a5;
            padding: 2px 10px; border-radius: 999px;
            font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em;
        }
        .badge-retry {
            background: #451a03; color: #fdba74;
            padding: 2px 10px; border-radius: 999px;
            font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em;
        }
        .section-label {
            color: #6b7280; font-size: 0.72rem; font-weight: 600;
            letter-spacing: 0.08em; text-transform: uppercase;
            margin-bottom: 0.25rem;
        }
        div[data-testid="stDataFrame"] {
            border: 1px solid #1e293b; border-radius: 6px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Render helper (defined before use) ───────────────────────────────────────

def render_assistant_message(meta: dict) -> None:
    """Render the structured pipeline output."""
    status    = meta.get("status", "failed")
    retry_att = meta.get("retry_attempted", False)
    retry_ok  = meta.get("retry_succeeded", False)
    sql       = meta.get("sql", "")
    result    = meta.get("result", [])
    error     = meta.get("error", "")

    badge_status = (
        '<span class="badge-success">SUCCESS</span>'
        if status == "success"
        else '<span class="badge-failed">FAILED</span>'
    )
    if retry_ok:
        badge_retry = '<span class="badge-retry">RETRY ✓</span>'
    elif retry_att:
        badge_retry = '<span class="badge-retry">RETRY ✗</span>'
    else:
        badge_retry = ""

    st.markdown(
        f'<div class="assistant-bubble">'
        f'<span class="section-label">Pipeline result</span><br>'
        f"{badge_status} {badge_retry}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if sql:
        st.markdown(
            '<div class="section-label">Generated SQL</div>',
            unsafe_allow_html=True,
        )
        safe_sql = (
            sql.replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;")
        )
        st.markdown(
            f'<div class="sql-block">{safe_sql}</div>',
            unsafe_allow_html=True,
        )

    if status == "success":
        if result:
            st.markdown(
                f'<div class="section-label">Results — {len(result)} row(s)</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(pd.DataFrame(result), use_container_width=True)
        else:
            st.info("Query executed successfully but returned 0 rows.")
    else:
        st.error(f"**Error:** {error}")

    decomp = meta.get("decomposition", {})
    if decomp:
        with st.expander("🔍 Query decomposition (Step 1 output)"):
            st.json(decomp)


# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🗄️ Text-to-SQL")
    st.markdown("**ClassicModels · PostgreSQL**")
    st.divider()

    db_ok = test_connection()
    if db_ok:
        st.success("Database connected", icon="✅")
    else:
        st.error("Database unreachable", icon="❌")

    st.divider()
    st.markdown("### 💡 Example questions")
    examples = [
        "List all product lines",
        "Which customers are from France?",
        "Top 5 products by MSRP",
        "Total revenue per order, top 10",
        "Employees who report to employee 1002",
        "Total payments per customer",
        "Orders in 'In Process' status",
        "All US offices",
        "Customer names with their sales rep",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True, key=f"ex_{ex}"):
            st.session_state["prefill"] = ex
            st.rerun()

    st.divider()
    st.markdown("### 📋 Recent executions")
    logs = read_logs(last_n=8)
    if logs:
        for entry in reversed(logs):
            icon  = "✅" if entry["status"] == "success" else "❌"
            retry = " 🔄" if entry.get("retry_attempted") else ""
            label = entry["question"]
            label = label[:40] + "…" if len(label) > 40 else label
            st.markdown(f"{icon}{retry} {label}")
    else:
        st.caption("No executions yet.")

    st.divider()
    if st.button("🗑️ Clear chat history", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


# ── Main content ──────────────────────────────────────────────────────────────
st.markdown("# Ask the database")
st.markdown(
    "Type a question in plain English. The pipeline will "
    "**decompose → generate SQL → validate → execute** — "
    "and self-correct with one retry if the first attempt fails."
)
st.divider()

# Replay chat history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(
            f'<div class="user-bubble">🧑 {msg["content"]}</div>',
            unsafe_allow_html=True,
        )
    else:
        render_assistant_message(msg.get("meta", {}))

# ── Input ─────────────────────────────────────────────────────────────────────
prefill  = st.session_state.pop("prefill", "")
question = st.chat_input(
    placeholder="e.g.  Which customers are from France?"
)

if prefill and not question:
    question = prefill

if question:
    st.session_state.messages.append(
        {"role": "user", "content": question, "meta": None}
    )
    st.markdown(
        f'<div class="user-bubble">🧑 {question}</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("⚙️ Running pipeline…"):
        output = run_pipeline(question)

    st.session_state.messages.append(
        {"role": "assistant", "content": question, "meta": output}
    )
    st.rerun()
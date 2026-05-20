"""Streamlit chat UI for the Text-to-SQL agent."""

from __future__ import annotations

import os

import streamlit as st

from app.config import APP_LOG_PATH, logger, settings
from app.db import check_database_connection
from app.graph.workflow import run_workflow

st.set_page_config(
    page_title="Text-to-SQL Agent",
    page_icon="🗄️",
    layout="wide",
)

st.title("Text-to-SQL Agent")
st.caption("Ask questions about the Classic Models database in natural language.")

with st.sidebar:
    st.header("Configuration")
    st.write(f"**LLM provider:** {settings.llm_provider}")
    st.write(f"**Max SQL retries:** {settings.max_sql_retries}")
    st.write(f"**Log file:** `{APP_LOG_PATH}`")
    db_ok = check_database_connection()
    st.write(f"**Database:** {'Connected' if db_ok else 'Unavailable'}")
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("meta"):
            with st.expander("Details"):
                st.json(message["meta"])

if prompt := st.chat_input("e.g. How many orders were shipped to customers in the USA?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if not db_ok:
            st.error("Database is not reachable. Start docker-compose and wait for Postgres.")
        elif not (settings.openai_api_key or settings.gemini_api_key):
            st.error("Set OPENAI_API_KEY or GEMINI_API_KEY in your .env file.")
        else:
            with st.spinner("Planning, generating SQL, validating, executing..."):
                logger.info("[Streamlit] User submitted query")
                state = run_workflow(prompt)

            answer = state.get("final_answer") or "No answer could be generated."
            st.markdown(answer)

            meta = {
                "plan": state.get("plan"),
                "sql": state.get("generated_sql"),
                "is_valid_sql": state.get("is_valid_sql"),
                "retry_count": state.get("retry_count"),
                "errors": state.get("errors"),
                "row_count": (state.get("execution_results") or {}).get("row_count", 0),
            }
            with st.expander("Pipeline details"):
                st.json(meta)
                results = state.get("execution_results") or {}
                if results.get("rows"):
                    st.dataframe(results["rows"], use_container_width=True)

            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "meta": meta}
            )

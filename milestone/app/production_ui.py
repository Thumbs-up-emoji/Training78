"""Milestone-5 Streamlit production UI.

A thin client for ``app/production_api.py``: takes a question, calls
``POST /query`` (with the ``X-API-Key`` header), shows the answer plus
governance metadata (routed capability/agent, HITL/guardrail block status,
groundedness-guard overrides, latency/cost/tokens), and lets the user submit
thumbs-up/down feedback for the specific ``trace_id`` via ``POST /feedback``.

This file intentionally contains **no business logic** -- it is a pure HTTP
client over the already-secured, already-traced, already-guarded production
API, so the UI and the API can be scaled/deployed independently.

Run with::

    streamlit run entrypoints/milestone5_production_ui.py
    # or directly:
    streamlit run app/production_ui.py

Configuration (environment variables):

- ``MILESTONE5_API_KEY``   -- the shared API key sent as ``X-API-Key``.
- ``MILESTONE5_API_BASE_URL`` -- base URL of the production API
  (default ``http://127.0.0.1:8000``).
- ``MILESTONE6_JWT_TOKEN`` -- short-lived bearer token required by M6.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"


def _api_base_url() -> str:
    return os.getenv("MILESTONE5_API_BASE_URL", DEFAULT_API_BASE_URL)


def _api_key() -> str | None:
    return os.getenv("MILESTONE5_API_KEY")


def _headers() -> dict[str, str]:
    key = _api_key()
    token = os.getenv("MILESTONE6_JWT_TOKEN")
    headers = {"X-API-Key": key} if key else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def call_query(query: str, thread_id: str | None = None) -> dict:
    payload: dict[str, str] = {"query": query}
    if thread_id:
        payload["thread_id"] = thread_id
    response = httpx.post(f"{_api_base_url()}/query", json=payload, headers=_headers(), timeout=60.0)
    response.raise_for_status()
    return response.json()


def call_feedback(trace_id: str, query: str, rating: str, comment: str | None = None) -> dict:
    payload = {"trace_id": trace_id, "query": query, "rating": rating, "comment": comment}
    response = httpx.post(f"{_api_base_url()}/feedback", json=payload, headers=_headers(), timeout=30.0)
    response.raise_for_status()
    return response.json()


def render() -> None:
    st.set_page_config(page_title="Milestone 5 - Governed Research Assistant", page_icon="🛡️")
    st.title("🛡️ Milestone 5 -- Governed Research Assistant")
    st.caption(
        "Authenticated, traced, groundedness-guarded front end for the "
        "Milestone-3/4 research + governance engine."
    )

    if not _api_key():
        st.warning(
            "MILESTONE5_API_KEY is not set in this environment -- requests to the "
            "production API will fail with 401. Set it before submitting a query."
        )
    if not os.getenv("MILESTONE6_JWT_TOKEN"):
        st.warning(
            "MILESTONE6_JWT_TOKEN is not set. Obtain a short-lived token from "
            "POST /auth/token before submitting a query."
        )

    if "last_result" not in st.session_state:
        st.session_state["last_result"] = None
    if "feedback_sent" not in st.session_state:
        st.session_state["feedback_sent"] = False

    with st.form("query_form"):
        query = st.text_area("Ask a question", placeholder="e.g. What is the enterprise security policy?")
        submitted = st.form_submit_button("Submit")

    if submitted and query.strip():
        st.session_state["feedback_sent"] = False
        try:
            with st.spinner("Routing through guardrails, retrieval, and the groundedness guard..."):
                result = call_query(query.strip())
            st.session_state["last_result"] = result
        except httpx.HTTPStatusError as error:
            st.session_state["last_result"] = None
            st.error(f"API error {error.response.status_code}: {error.response.text}")
        except httpx.HTTPError as error:
            st.session_state["last_result"] = None
            st.error(f"Could not reach the production API at {_api_base_url()}: {error}")

    result = st.session_state.get("last_result")
    if result:
        st.subheader("Answer")
        if result.get("blocked"):
            st.error("This request was blocked or the answer was withheld -- see details below.")
        st.write(result.get("answer") or "_(no answer returned)_")

        if result.get("groundedness_override"):
            st.info(
                "⚠️ Groundedness guard overrode the underlying engine's answer: "
                f"{result.get('groundedness_override_reason')}"
            )

        with st.expander("Governance & trace details"):
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Routed capability", result.get("routed_capability") or "n/a")
                st.metric("Routed agent", result.get("routed_agent") or "n/a")
                st.metric("Latency (ms)", round(result.get("latency_ms", 0.0), 2))
            with col2:
                st.metric("Tokens (estimate)", result.get("tokens_estimate", 0))
                st.metric("Cost (USD, estimate)", f"${result.get('cost_estimate_usd', 0.0):.6f}")
                st.metric("Blocked", str(result.get("blocked")))
            st.code(f"trace_id: {result.get('trace_id')}\nthread_id: {result.get('thread_id')}")

        st.subheader("Was this answer helpful?")
        feedback_col1, feedback_col2 = st.columns(2)
        disabled = st.session_state.get("feedback_sent", False)
        if feedback_col1.button("👍 Helpful", disabled=disabled):
            call_feedback(result["trace_id"], result["query"], "up")
            st.session_state["feedback_sent"] = True
            st.success("Thanks for your feedback!")
        if feedback_col2.button("👎 Not helpful", disabled=disabled):
            call_feedback(result["trace_id"], result["query"], "down")
            st.session_state["feedback_sent"] = True
            st.success("Thanks for your feedback!")


render()

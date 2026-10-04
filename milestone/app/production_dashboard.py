"""Milestone-5 Streamlit monitoring dashboard.

Reads the durable JSONL evidence produced by ``app/production_api.py``
(``logs/spans.jsonl`` via ``app.ops.instrumentation.Tracer`` and
``logs/feedback.jsonl`` via ``app.ops.feedback``) and renders top-line
metrics and charts: request volume, p50/p95 latency, error rate, cost over
time, and feedback satisfaction rate.

All data loading/aggregation lives in ``app/ops/dashboard_data.py`` (pure,
Streamlit-free functions, unit-tested independently); this file is
presentation-only.

Run with::

    streamlit run entrypoints/milestone5_dashboard.py --server.port 8502
    # or directly:
    streamlit run app/production_dashboard.py --server.port 8502
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from app.ops.dashboard_data import (
    DEFAULT_FEEDBACK_LOG_PATH,
    DEFAULT_SPAN_LOG_PATH,
    cost_over_time,
    load_feedback,
    load_spans,
    request_spans,
    requests_over_time,
    summarize,
)


@st.cache_data(ttl=15)
def _load(span_log_path: str, feedback_log_path: str) -> tuple[list[dict], list[dict]]:
    return load_spans(span_log_path), load_feedback(feedback_log_path)


def render() -> None:
    st.set_page_config(page_title="Milestone 5 - Monitoring Dashboard", page_icon="📊", layout="wide")
    st.title("📊 Milestone 5 -- Monitoring Dashboard")
    st.caption("Live metrics computed from logs/spans.jsonl and logs/feedback.jsonl.")

    span_log_path = os.getenv("MILESTONE5_SPAN_LOG_PATH", str(DEFAULT_SPAN_LOG_PATH))
    feedback_log_path = os.getenv("MILESTONE5_FEEDBACK_LOG_PATH", str(DEFAULT_FEEDBACK_LOG_PATH))

    if st.button("🔄 Refresh"):
        _load.clear()

    spans, feedback_entries = _load(span_log_path, feedback_log_path)
    top_level = request_spans(spans)

    if not top_level:
        st.info(
            "No requests logged yet. Send a query through the production API "
            "(`app/production_api.py`) or the UI (`app/production_ui.py`) to "
            "populate this dashboard."
        )
        return

    summary = summarize(spans, feedback_entries)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Requests", summary["request_volume"])
    col2.metric("p50 latency (ms)", round(summary["p50_ms"], 1) if summary["p50_ms"] is not None else "n/a")
    col3.metric("p95 latency (ms)", round(summary["p95_ms"], 1) if summary["p95_ms"] is not None else "n/a")
    col4.metric("Error rate", f"{summary['error_rate']:.1%}" if summary["error_rate"] is not None else "n/a")
    col5.metric("Total cost (USD)", f"${summary['total_cost_usd']:.4f}")

    if summary.get("feedback_count"):
        rate = summary.get("feedback_satisfaction_rate")
        st.metric(
            "Feedback satisfaction",
            f"{rate:.1%}" if rate is not None else "n/a",
            help=f"{summary['feedback_count']} feedback entries recorded",
        )

    st.subheader("Requests over time")
    request_counts = requests_over_time(top_level, bucket="minute")
    if request_counts:
        df_requests = pd.DataFrame(
            {"timestamp": list(request_counts.keys()), "requests": list(request_counts.values())}
        ).set_index("timestamp")
        st.bar_chart(df_requests)

    st.subheader("Cost over time (USD)")
    cost_counts = cost_over_time(top_level, bucket="minute")
    if cost_counts:
        df_cost = pd.DataFrame(
            {"timestamp": list(cost_counts.keys()), "cost_usd": list(cost_counts.values())}
        ).set_index("timestamp")
        st.line_chart(df_cost)

    st.subheader("Capability routing breakdown")
    capability_counts: dict[str, int] = {}
    for span in top_level:
        capability = span.get("attributes", {}).get("routed_capability") or "unknown"
        capability_counts[capability] = capability_counts.get(capability, 0) + 1
    if capability_counts:
        df_capability = pd.DataFrame(
            {"capability": list(capability_counts.keys()), "count": list(capability_counts.values())}
        ).set_index("capability")
        st.bar_chart(df_capability)

    with st.expander("Raw span records"):
        st.dataframe(pd.DataFrame(top_level))

    if feedback_entries:
        with st.expander("Raw feedback records"):
            st.dataframe(pd.DataFrame(feedback_entries))


render()

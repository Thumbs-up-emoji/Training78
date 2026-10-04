"""Pure, Streamlit-free data-loading and metric-computation functions for the
Milestone-5 monitoring dashboard (``app/production_dashboard.py``).

Kept separate from the Streamlit rendering code so these functions can be
unit-tested directly (``tests/test_milestone5_production.py``) without
importing/running Streamlit.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_SPAN_LOG_PATH = Path("logs") / "spans.jsonl"
DEFAULT_FEEDBACK_LOG_PATH = Path("logs") / "feedback.jsonl"


def load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Reads a JSONL file into a list of dicts. Returns ``[]`` if the file does
    not exist. Silently skips malformed lines (defensive against a partial
    write mid-crash) rather than failing the whole dashboard.
    """
    resolved = Path(path)
    if not resolved.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in resolved.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def load_spans(path: Path | str = DEFAULT_SPAN_LOG_PATH) -> list[dict[str, Any]]:
    return load_jsonl(path)


def load_feedback(path: Path | str = DEFAULT_FEEDBACK_LOG_PATH) -> list[dict[str, Any]]:
    return load_jsonl(path)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile (``p`` in ``[0, 100]``) with linear
    interpolation between the two closest ranks. Returns ``None`` for an empty
    input rather than raising, since dashboards must render gracefully before
    any traffic has been logged.
    """
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (p / 100) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    fraction = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def request_spans(spans: list[dict[str, Any]], name: str = "governance.handle_request") -> list[dict[str, Any]]:
    """Filters to the top-level per-request span (as opposed to nested
    sub-spans), which is what latency/cost/error/volume metrics are computed
    over. Falls back to all spans if none match ``name`` (e.g. a differently
    named tracer was used).
    """
    matching = [span for span in spans if span.get("name") == name]
    return matching or spans


def latency_percentiles(spans: list[dict[str, Any]]) -> dict[str, float | None]:
    durations = [span["duration_ms"] for span in spans if isinstance(span.get("duration_ms"), (int, float))]
    return {"p50_ms": percentile(durations, 50), "p95_ms": percentile(durations, 95)}


def error_rate(spans: list[dict[str, Any]]) -> float | None:
    if not spans:
        return None
    errors = sum(1 for span in spans if span.get("status") == "error")
    return round(errors / len(spans), 4)


def total_cost_usd(spans: list[dict[str, Any]]) -> float:
    return round(sum(float(span.get("attributes", {}).get("cost_usd", 0.0) or 0.0) for span in spans), 6)


def _bucket_key(timestamp: str, bucket: str = "minute") -> str:
    # ISO timestamps look like 2024-01-01T12:34:56.789+00:00 -- truncate to the
    # desired granularity without needing a full datetime parse/round-trip.
    if bucket == "hour":
        return timestamp[:13]
    return timestamp[:16]


def requests_over_time(spans: list[dict[str, Any]], bucket: str = "minute") -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for span in spans:
        start = span.get("start_time")
        if not start:
            continue
        counts[_bucket_key(start, bucket)] += 1
    return dict(sorted(counts.items()))


def cost_over_time(spans: list[dict[str, Any]], bucket: str = "minute") -> dict[str, float]:
    costs: dict[str, float] = defaultdict(float)
    for span in spans:
        start = span.get("start_time")
        if not start:
            continue
        cost = span.get("attributes", {}).get("cost_usd", 0.0) or 0.0
        costs[_bucket_key(start, bucket)] += float(cost)
    return {key: round(value, 6) for key, value in sorted(costs.items())}


def feedback_satisfaction_rate(feedback_entries: list[dict[str, Any]]) -> float | None:
    if not feedback_entries:
        return None
    up_votes = sum(1 for entry in feedback_entries if entry.get("rating") == "up")
    return round(up_votes / len(feedback_entries), 4)


def summarize(spans: list[dict[str, Any]], feedback_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One-shot summary dict for the dashboard's top-line metric row."""
    top_level = request_spans(spans)
    summary: dict[str, Any] = {
        "request_volume": len(top_level),
        **latency_percentiles(top_level),
        "error_rate": error_rate(top_level),
        "total_cost_usd": total_cost_usd(top_level),
    }
    if feedback_entries is not None:
        summary["feedback_satisfaction_rate"] = feedback_satisfaction_rate(feedback_entries)
        summary["feedback_count"] = len(feedback_entries)
    return summary

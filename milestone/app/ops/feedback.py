"""Milestone-5 user feedback capture (thumbs-up/down + optional comment).

Used by ``app/production_ui.py`` (Streamlit) after every answer is rendered,
and exposed as a ``POST /feedback`` route on ``app/production_api.py``.
Feedback is appended as JSONL so the monitoring dashboard
(``app/production_dashboard.py``) can compute a satisfaction rate alongside
latency/cost/error metrics.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_FEEDBACK_LOG_PATH = Path("logs") / "feedback.jsonl"

_write_lock = threading.Lock()

Rating = Literal["up", "down"]


class FeedbackModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeedbackEntry(FeedbackModel):
    trace_id: str
    query: str
    rating: Rating
    comment: str | None = None
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def record_feedback(
    trace_id: str,
    query: str,
    rating: Rating,
    comment: str | None = None,
    log_path: Path | str | None = None,
) -> FeedbackEntry:
    """Appends one feedback record to the feedback JSONL log and returns it."""
    entry = FeedbackEntry(trace_id=trace_id, query=query, rating=rating, comment=comment)
    resolved_path = Path(log_path) if log_path else DEFAULT_FEEDBACK_LOG_PATH
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with resolved_path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
    return entry


def load_feedback(log_path: Path | str | None = None) -> list[FeedbackEntry]:
    """Reads all feedback entries back from the JSONL log (empty list if the
    file does not exist yet).
    """
    resolved_path = Path(log_path) if log_path else DEFAULT_FEEDBACK_LOG_PATH
    if not resolved_path.exists():
        return []
    entries: list[FeedbackEntry] = []
    for line in resolved_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(FeedbackEntry.model_validate(json.loads(line)))
    return entries

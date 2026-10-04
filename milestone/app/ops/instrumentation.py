"""Milestone-5 lightweight tracing/instrumentation.

Not the official OpenTelemetry SDK (kept dependency-free, matching this
repo's convention for MCP/A2A) but implements the same core concepts an
OTel-style tracer provides: a shared ``trace_id`` per top-level request, one
``Span`` per logical unit of work (name, start/end time, duration, status,
arbitrary attributes), and a durable, structured (JSONL) export target so a
monitoring dashboard can read spans back without a collector.

Usage::

    tracer = get_tracer("production_api")
    with tracer.trace() as trace_id:          # new shared trace_id
        with tracer.span("governance.handle_request", query=query) as span:
            response = platform.handle_request(query=query, thread_id=trace_id)
            span.set_attribute("tokens", estimate_tokens(response.answer or ""))
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_SPAN_LOG_PATH = Path("logs") / "spans.jsonl"

# Rough, offline-deterministic cost model (USD per 1,000 tokens), loosely
# modeled on a small hosted-LLM price point. Swappable via `cost_per_1k_tokens`
# on `Tracer` -- there is no live billing API call here, this is an estimate
# for dashboarding purposes only.
DEFAULT_COST_PER_1K_TOKENS_USD = 0.002

_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "milestone5_trace_id", default=None
)

_LOG = logging.getLogger("milestone5_instrumentation")


def estimate_tokens(text: str) -> int:
    """Deterministic, offline token-count estimate (~4 chars/token), used in
    place of a real tokenizer so span cost/size accounting works without any
    model provider dependency.
    """
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def estimate_cost_usd(tokens: int, cost_per_1k_tokens: float = DEFAULT_COST_PER_1K_TOKENS_USD) -> float:
    """Deterministic estimated USD cost for a given token count."""
    return round((tokens / 1000) * cost_per_1k_tokens, 6)


def new_trace_id() -> str:
    return uuid4().hex


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str = field(default_factory=lambda: uuid4().hex)
    start_time: float = field(default_factory=time.perf_counter)
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None
    _start_wall: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    _end_wall: str | None = None
    duration_ms: float | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_error(self, message: str) -> None:
        self.status = "error"
        self.error = message

    def to_record(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "start_time": self._start_wall,
            "end_time": self._end_wall,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "attributes": self.attributes,
        }


class Tracer:
    """Writes one JSON line per completed span to ``log_path`` (created if
    missing). Thread-safe append via a lock, since Streamlit/uvicorn may serve
    concurrent requests.
    """

    def __init__(
        self,
        name: str,
        log_path: Path | str | None = None,
        cost_per_1k_tokens: float = DEFAULT_COST_PER_1K_TOKENS_USD,
    ):
        self.name = name
        self.log_path = Path(log_path) if log_path else DEFAULT_SPAN_LOG_PATH
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self._lock = threading.Lock()

    @contextmanager
    def trace(self, trace_id: str | None = None) -> Iterator[str]:
        """Establishes a shared ``trace_id`` for every span opened underneath
        this context manager (e.g. one per inbound HTTP/UI request).
        """
        resolved = trace_id or new_trace_id()
        token = _current_trace_id.set(resolved)
        try:
            yield resolved
        finally:
            _current_trace_id.reset(token)

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        trace_id = _current_trace_id.get() or new_trace_id()
        span = Span(name=name, trace_id=trace_id, attributes=dict(attributes))
        try:
            yield span
        except Exception as error:  # noqa: BLE001 - record then re-raise
            span.set_error(str(error))
            raise
        finally:
            span.duration_ms = round((time.perf_counter() - span.start_time) * 1000, 3)
            span._end_wall = datetime.now(timezone.utc).isoformat()
            self._write(span)

    def _write(self, span: Span) -> None:
        record = span.to_record()
        record["tracer"] = self.name
        line = json.dumps(record, default=str)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        _LOG.debug("span recorded: %s", record["name"])

    def estimate_cost(self, tokens: int) -> float:
        return estimate_cost_usd(tokens, self.cost_per_1k_tokens)


_tracers: dict[str, Tracer] = {}
_tracers_lock = threading.Lock()


def get_tracer(name: str = "milestone5", log_path: Path | str | None = None) -> Tracer:
    """Returns a process-wide singleton ``Tracer`` per name (mirroring
    ``logging.getLogger`` semantics) so every module that calls
    ``get_tracer("production_api")`` shares one span log and lock.
    """
    key = f"{name}::{Path(log_path).resolve() if log_path else DEFAULT_SPAN_LOG_PATH.resolve()}"
    with _tracers_lock:
        if key not in _tracers:
            _tracers[key] = Tracer(name, log_path=log_path)
        return _tracers[key]

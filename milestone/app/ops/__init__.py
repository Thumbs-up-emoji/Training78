"""Milestone-5 operations package: API-key auth, lightweight tracing/cost
instrumentation, feedback capture, golden-set evaluation, and dashboard data
helpers -- the observability/security/eval layer added on top of the
unchanged Milestone-3/4 engine.
"""

from __future__ import annotations

from app.ops.auth import verify_api_key
from app.ops.eval_metrics import answer_relevancy, mean_reciprocal_rank, refusal_detected, retrieval_hit
from app.ops.feedback import FeedbackEntry, load_feedback, record_feedback
from app.ops.golden_eval import GoldenEvalReport, load_golden_cases, run_golden_eval
from app.ops.instrumentation import Tracer, estimate_cost_usd, estimate_tokens, get_tracer, new_trace_id

__all__ = [
    "verify_api_key",
    "answer_relevancy",
    "mean_reciprocal_rank",
    "refusal_detected",
    "retrieval_hit",
    "FeedbackEntry",
    "load_feedback",
    "record_feedback",
    "GoldenEvalReport",
    "load_golden_cases",
    "run_golden_eval",
    "Tracer",
    "estimate_cost_usd",
    "estimate_tokens",
    "get_tracer",
    "new_trace_id",
]

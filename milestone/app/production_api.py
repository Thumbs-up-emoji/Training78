"""Milestone-6 secured production API.

A thin, additive FastAPI wrapper around the unchanged Milestone-4
``GovernancePlatform`` (which itself wraps the unchanged Milestone-3
``ResearchAssistant`` engine). This module never modifies ``app/core.py`` or
``app/governance/*`` -- it only *secures*, *observes*, and *safety-checks*
what those layers already produce:

- **Auth**: every route requires the ``X-API-Key`` header. In addition,
    ``/health``, ``/query``, and ``/feedback`` require a short-lived bearer JWT;
    ``/auth/token`` issues that token only after API-key and demo-account
    validation.
- **Instrumentation**: every request is wrapped in an ``app.ops.instrumentation
  .Tracer`` trace + span, giving each request a shared ``trace_id``, a
  duration, and an estimated token/cost figure, all durably logged to
  ``logs/spans.jsonl`` for ``app/production_dashboard.py`` to read back.
- **Groundedness guard**: before an answer is returned, it is passed through
  ``app.ops.groundedness_guard.apply_groundedness_guard`` so a confidently-
  fabricated answer (entity or attribute absent from the retrieved content)
  is replaced with an explicit refusal rather than presented as fact.
- **Feedback**: ``POST /feedback`` records a thumbs-up/down (+ optional
  comment) against a ``trace_id``, appended to ``logs/feedback.jsonl``.

Endpoints:

- ``POST /auth/token`` -- issue a short-lived JWT after API-key validation.
- ``GET  /health``    -- service heartbeat.
- ``POST /query``     -- governed, traced, groundedness-guarded query.
- ``POST /feedback``  -- record user feedback for a prior ``trace_id``.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.governance.platform import GovernancePlatform
from app.governance.rag_sql import GOVERNANCE_TABLES
from app.ops.auth import create_access_token, verify_api_key, verify_bearer_token, verify_demo_credentials
from app.ops.feedback import FeedbackEntry, Rating, record_feedback
from app.ops.groundedness_guard import apply_groundedness_guard
from app.ops.instrumentation import DEFAULT_SPAN_LOG_PATH, Tracer, estimate_tokens


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryRequest(APIModel):
    query: str = Field(min_length=3)
    thread_id: str | None = None


class QueryResponse(APIModel):
    trace_id: str
    thread_id: str
    query: str
    answer: str | None
    blocked: bool
    routed_capability: str | None = None
    routed_agent: str | None = None
    groundedness_override: bool
    groundedness_override_reason: str | None = None
    tokens_estimate: int
    cost_estimate_usd: float
    latency_ms: float


class FeedbackRequest(APIModel):
    trace_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    rating: Rating
    comment: str | None = None


class HealthResponse(APIModel):
    status: str
    service: str
    spans_log: str
    feedback_log: str


class TokenRequest(APIModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"


def create_app(
    workspace_root: Path | str | None = None,
    platform: GovernancePlatform | None = None,
    span_log_path: Path | str | None = None,
    feedback_log_path: Path | str | None = None,
) -> FastAPI:
    load_dotenv()
    root = Path(workspace_root or Path(__file__).parents[1]).resolve()
    governance_platform = platform or GovernancePlatform(workspace_root=root)
    tracer = Tracer(name="production_api", log_path=span_log_path or DEFAULT_SPAN_LOG_PATH)
    resolved_feedback_log_path = (
        Path(feedback_log_path) if feedback_log_path else Path("logs") / "feedback.jsonl"
    )

    application = FastAPI(
        title="Milestone 6 Production API",
        version="2.0.0",
        description=(
            "API-key and JWT authenticated, traced, groundedness-guarded production surface for the "
            "Milestone-3/4 research + governance engine."
        ),
        dependencies=[Depends(verify_api_key)],
    )
    application.state.governance_platform = governance_platform
    application.state.tracer = tracer

    @application.post("/auth/token", response_model=TokenResponse)
    def issue_token(request: TokenRequest) -> TokenResponse:
        """Issue a short-lived demo JWT after the API-key gateway has accepted the request."""
        subject = verify_demo_credentials(request.username, request.password)
        return TokenResponse(access_token=create_access_token(subject))

    @application.get("/health", response_model=HealthResponse, dependencies=[Depends(verify_bearer_token)])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="milestone6-production-api",
            spans_log=str(tracer.log_path),
            feedback_log=str(resolved_feedback_log_path),
        )

    @application.post("/query", response_model=QueryResponse, dependencies=[Depends(verify_bearer_token)])
    def query(request: QueryRequest) -> QueryResponse:
        thread_id = request.thread_id or f"production-{uuid4()}"
        with tracer.trace() as trace_id:
            with tracer.span("governance.handle_request", query=request.query, thread_id=thread_id) as span:
                try:
                    response = governance_platform.handle_request(query=request.query, thread_id=thread_id)
                except (OSError, ValueError, RuntimeError, LookupError) as error:
                    span.set_error(str(error))
                    raise HTTPException(status_code=422, detail=str(error)) from error

                final_answer, overridden, reason = apply_groundedness_guard(
                    request.query,
                    response.routed_capability,
                    response.answer,
                    database_path=governance_platform.governance_db_path,
                    allowed_tables=GOVERNANCE_TABLES,
                )
                tokens = estimate_tokens(final_answer or "")
                cost = tracer.estimate_cost(tokens)
                span.set_attribute("routed_capability", response.routed_capability)
                span.set_attribute("routed_agent", response.routed_agent)
                span.set_attribute("blocked", response.blocked)
                span.set_attribute("groundedness_override", overridden)
                span.set_attribute("tokens", tokens)
                span.set_attribute("cost_usd", cost)

            return QueryResponse(
                trace_id=trace_id,
                thread_id=thread_id,
                query=request.query,
                answer=final_answer,
                blocked=response.blocked or overridden,
                routed_capability=response.routed_capability,
                routed_agent=response.routed_agent,
                groundedness_override=overridden,
                groundedness_override_reason=reason,
                tokens_estimate=tokens,
                cost_estimate_usd=cost,
                latency_ms=span.duration_ms or 0.0,
            )

    @application.post("/feedback", response_model=FeedbackEntry, dependencies=[Depends(verify_bearer_token)])
    def feedback(request: FeedbackRequest) -> FeedbackEntry:
        return record_feedback(
            trace_id=request.trace_id,
            query=request.query,
            rating=request.rating,
            comment=request.comment,
            log_path=resolved_feedback_log_path,
        )

    return application


app = create_app()

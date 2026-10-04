"""Milestone-5 production/observability/security layer tests.

Covers what Milestone 4's suites don't: API-key auth enforcement on
``app/production_api.py``, span instrumentation shape/trace_id sharing,
feedback round-tripping, the groundedness guard, and the pure
``app/ops/dashboard_data.py`` functions the monitoring dashboard renders.
Runtime state (span/feedback logs, governance runtime paths) is isolated per
test via ``tmp_path``, matching the pattern used by
``tests/test_milestone5_regression.py`` / ``tests/test_milestone5_governance.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.governance.platform import GovernancePlatform
from app.ops.auth import API_KEY_ENV_VAR
from app.ops.dashboard_data import (
    cost_over_time,
    error_rate,
    latency_percentiles,
    load_jsonl,
    percentile,
    request_spans,
    requests_over_time,
    summarize,
)
from app.ops.eval_metrics import answer_relevancy, mean_reciprocal_rank, refusal_detected, retrieval_hit
from app.ops.feedback import load_feedback, record_feedback
from app.ops.golden_eval import load_golden_cases, run_golden_eval
from app.ops.groundedness_guard import apply_groundedness_guard, extract_entity_terms
from app.ops.instrumentation import Tracer, estimate_cost_usd, estimate_tokens
from app.production_api import create_app

WORKSPACE_ROOT = Path(__file__).parents[1]
TEST_API_KEY = "test-key-12345"


@pytest.fixture(scope="session")
def platform(tmp_path_factory: pytest.TempPathFactory) -> GovernancePlatform:
    runtime_path = tmp_path_factory.mktemp("milestone5-production-runtime")
    return GovernancePlatform(
        workspace_root=WORKSPACE_ROOT,
        database_path=runtime_path / "sales.db",
        memory_path=runtime_path / "memory.db",
        approval_path=runtime_path / "approval_queue.json",
        log_path=runtime_path / "governance.jsonl",
        governance_database_path=runtime_path / "governance.db",
        use_llm=False,
    )


@pytest.fixture()
def span_log_path(tmp_path: Path) -> Path:
    return tmp_path / "spans.jsonl"


@pytest.fixture()
def feedback_log_path(tmp_path: Path) -> Path:
    return tmp_path / "feedback.jsonl"


@pytest.fixture()
def api_client(
    platform: GovernancePlatform,
    span_log_path: Path,
    feedback_log_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)
    monkeypatch.setenv("MILESTONE5_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("MILESTONE6_DEMO_PASSWORD", "test-demo-password")
    application = create_app(
        platform=platform,
        span_log_path=span_log_path,
        feedback_log_path=feedback_log_path,
    )
    return TestClient(application)


@pytest.fixture()
def auth_headers(api_client: TestClient) -> dict[str, str]:
    token_response = api_client.post(
        "/auth/token",
        json={"username": "demo-user", "password": "test-demo-password"},
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert token_response.status_code == 200
    return {"X-API-Key": TEST_API_KEY, "Authorization": f"Bearer {token_response.json()['access_token']}"}


# ---------------------------------------------------------------------------
# API-key authentication
# ---------------------------------------------------------------------------


def test_health_requires_api_key(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    unauthenticated = api_client.get("/health")
    assert unauthenticated.status_code == 401

    authenticated = api_client.get("/health", headers=auth_headers)
    assert authenticated.status_code == 200
    assert authenticated.json()["status"] == "ok"


def test_query_rejects_missing_or_wrong_api_key(api_client: TestClient) -> None:
    missing = api_client.post("/query", json={"query": "What is our data retention policy?"})
    assert missing.status_code == 401

    wrong = api_client.post(
        "/query",
        json={"query": "What is our data retention policy?"},
        headers={"X-API-Key": "not-the-right-key"},
    )
    assert wrong.status_code == 401


def test_query_succeeds_with_valid_api_key(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    response = api_client.post(
        "/query",
        json={"query": "What is our data retention policy?"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"]
    assert "cost_estimate_usd" in body
    assert "tokens_estimate" in body


def test_missing_server_key_fails_closed(
    platform: GovernancePlatform,
    span_log_path: Path,
    feedback_log_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    application = create_app(platform=platform, span_log_path=span_log_path, feedback_log_path=feedback_log_path)
    client = TestClient(application)
    response = client.get("/health", headers={"X-API-Key": "anything"})
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Instrumentation: spans written with required fields + shared trace_id
# ---------------------------------------------------------------------------


def test_query_writes_span_with_required_fields_and_shared_trace_id(
    api_client: TestClient, span_log_path: Path, auth_headers: dict[str, str]
) -> None:
    response = api_client.post(
        "/query",
        json={"query": "What is our data retention policy?"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    trace_id = response.json()["trace_id"]

    assert span_log_path.exists()
    records = [json.loads(line) for line in span_log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records
    matching = [record for record in records if record["trace_id"] == trace_id]
    assert matching, "no span recorded under the trace_id returned to the caller"
    for record in matching:
        assert record["name"]
        assert isinstance(record["duration_ms"], (int, float))
        assert "cost_usd" in record["attributes"]
        assert "tokens" in record["attributes"]


def test_tracer_estimate_cost_and_tokens_are_deterministic() -> None:
    tokens = estimate_tokens("hello world this is a test")
    assert tokens > 0
    cost = estimate_cost_usd(tokens, cost_per_1k_tokens=0.002)
    assert cost == round((tokens / 1000) * 0.002, 6)


def test_tracer_span_context_manager_writes_one_line_per_span(tmp_path: Path) -> None:
    log_path = tmp_path / "spans.jsonl"
    tracer = Tracer(name="unit-test", log_path=log_path)
    with tracer.trace() as trace_id:
        with tracer.span("step-one"):
            pass
        with tracer.span("step-two"):
            pass
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        record = json.loads(line)
        assert record["trace_id"] == trace_id


# ---------------------------------------------------------------------------
# Feedback capture
# ---------------------------------------------------------------------------


def test_feedback_round_trips_through_api(
    api_client: TestClient, feedback_log_path: Path, auth_headers: dict[str, str]
) -> None:
    response = api_client.post(
        "/feedback",
        json={"trace_id": "trace-123", "query": "test query", "rating": "up", "comment": "great"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["rating"] == "up"

    loaded = load_feedback(feedback_log_path)
    assert len(loaded) == 1
    assert loaded[0].trace_id == "trace-123"


def test_record_feedback_appends_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "feedback.jsonl"
    record_feedback(trace_id="t1", query="q1", rating="down", log_path=log_path)
    record_feedback(trace_id="t2", query="q2", rating="up", log_path=log_path)
    entries = load_feedback(log_path)
    assert [entry.trace_id for entry in entries] == ["t1", "t2"]


# ---------------------------------------------------------------------------
# Groundedness guard
# ---------------------------------------------------------------------------


def test_groundedness_guard_flags_absent_named_entity() -> None:
    final_answer, overridden, reason = apply_groundedness_guard(
        question="What is DataSphere 1's Net Promoter Score (NPS)?",
        capability="full_research",
        answer_text="This report addresses: What is DataSphere 1's Net Promoter Score (NPS)?\nNo grounded evidence was available for this request.",
    )
    assert overridden
    assert "DataSphere" in reason
    assert final_answer != "This report addresses: What is DataSphere 1's Net Promoter Score (NPS)?"


def test_groundedness_guard_allows_answer_mentioning_the_entity() -> None:
    final_answer, overridden, _ = apply_groundedness_guard(
        question="What is Acme Corp's market share?",
        capability="rag",
        answer_text="Acme Corp holds 32.5% market share according to competitors.csv.",
    )
    assert not overridden
    assert final_answer == "Acme Corp holds 32.5% market share according to competitors.csv."


def test_extract_entity_terms_ignores_generic_acronyms() -> None:
    terms = extract_entity_terms("What does the FAQ say about SQL validation?")
    assert "FAQ" not in terms
    assert "SQL" not in terms


# ---------------------------------------------------------------------------
# Eval metrics (reference-free)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("I don't know.", True),
        ("I do not have enough information to answer that.", True),
        ("No matching governance records found.", True),
        (None, True),
        ("", True),
        ("Acme Corp holds 32.5% market share.", False),
    ],
)
def test_refusal_detected(answer: str | None, expected: bool) -> None:
    assert refusal_detected(answer) is expected


def test_answer_relevancy_scores_higher_for_overlapping_text() -> None:
    high = answer_relevancy("the market share of Acme Corp is 32.5 percent", "what is Acme Corp's market share")
    low = answer_relevancy("bananas are yellow", "what is Acme Corp's market share")
    assert high > low


def test_retrieval_hit_and_mrr_none_when_no_expected_source() -> None:
    assert retrieval_hit(None, ["FAQ.docx"]) is None
    assert mean_reciprocal_rank(None, ["FAQ.docx"]) is None


def test_retrieval_hit_and_mrr_match_loosely() -> None:
    assert retrieval_hit("FAQ_Document.docx", ["some/path/FAQ.docx"]) is True
    assert mean_reciprocal_rank("FAQ_Document.docx", ["Enterprise_Policies.md", "FAQ.docx"]) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Golden-set evaluation script
# ---------------------------------------------------------------------------


def test_golden_set_loads_all_12_questions_with_3_adversarial() -> None:
    cases = load_golden_cases()
    assert len(cases) == 12
    adversarial = [case for case in cases if case.is_adversarial]
    assert len(adversarial) == 3
    assert {case.id for case in adversarial} == {"q10", "q11", "q12"}


def test_golden_eval_report_scores_adversarial_refusals(platform: GovernancePlatform) -> None:
    cases = load_golden_cases()
    report = run_golden_eval(platform, cases)
    assert report.total_cases == 12
    assert report.adversarial_cases == 3
    assert report.adversarial_refusal_rate == 1.0
    for result in report.results:
        if result.is_adversarial:
            assert result.passed, f"{result.case_id} fabricated an answer instead of refusing"


# ---------------------------------------------------------------------------
# Dashboard data (pure functions, no Streamlit import required)
# ---------------------------------------------------------------------------


def test_percentile_handles_empty_and_single_value() -> None:
    assert percentile([], 50) is None
    assert percentile([42.0], 95) == 42.0


def test_percentile_p50_p95_on_known_distribution() -> None:
    values = [float(value) for value in range(1, 101)]
    assert percentile(values, 50) == pytest.approx(50.5, abs=1.0)
    assert percentile(values, 95) == pytest.approx(95.05, abs=1.0)


def test_load_jsonl_skips_malformed_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "spans.jsonl"
    log_path.write_text('{"a": 1}\nnot-json\n{"a": 2}\n', encoding="utf-8")
    records = load_jsonl(log_path)
    assert records == [{"a": 1}, {"a": 2}]


def test_dashboard_summarize_computes_latency_error_and_cost(tmp_path: Path) -> None:
    spans = [
        {
            "name": "governance.handle_request",
            "duration_ms": 100.0,
            "status": "ok",
            "start_time": "2026-01-01T00:00:00+00:00",
            "attributes": {"cost_usd": 0.001},
        },
        {
            "name": "governance.handle_request",
            "duration_ms": 200.0,
            "status": "error",
            "start_time": "2026-01-01T00:01:00+00:00",
            "attributes": {"cost_usd": 0.002},
        },
    ]
    top_level = request_spans(spans)
    assert len(top_level) == 2
    latency = latency_percentiles(top_level)
    assert latency["p50_ms"] is not None
    assert error_rate(top_level) == 0.5
    summary = summarize(spans)
    assert summary["request_volume"] == 2
    assert summary["total_cost_usd"] == pytest.approx(0.003)

    requests_by_minute = requests_over_time(top_level, bucket="minute")
    assert sum(requests_by_minute.values()) == 2
    cost_by_minute = cost_over_time(top_level, bucket="minute")
    assert sum(cost_by_minute.values()) == pytest.approx(0.003)

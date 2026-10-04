from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from entrypoints.milestone5_api import create_app
from entrypoints.milestone5_core import (
    ApprovalUpdate,
    MemorySearchInput,
    MemoryWriteInput,
    ResearchAssistant,
    SQLiteMemoryStore,
    TextToSQLInput,
    bootstrap_enterprise_database,
)


WORKSPACE_ROOT = Path(__file__).parents[1]

SYNTHETIC_SCENARIOS = [
    pytest.param(
        "Which products generated the highest total revenue?",
        "text_to_sql",
        id="top-product-revenue",
    ),
    pytest.param(
        "Compare total profit by product.",
        "text_to_sql",
        id="product-profit",
    ),
    pytest.param(
        "Show revenue by region.",
        "text_to_sql",
        id="regional-revenue",
    ),
    pytest.param(
        "Rank categories by units sold.",
        "text_to_sql",
        id="category-units",
    ),
    pytest.param(
        "Which products have the lowest revenue?",
        "text_to_sql",
        id="lowest-product-revenue",
    ),
    pytest.param(
        "Show monthly sales revenue.",
        "text_to_sql",
        id="monthly-revenue",
    ),
    pytest.param(
        "What is the status of order 1004?",
        "text_to_sql",
        id="order-status",
    ),
    pytest.param(
        "Which payment method was used for order 1005?",
        "text_to_sql",
        id="order-payment",
    ),
    pytest.param(
        "Summarize delivered order counts and amounts.",
        "text_to_sql",
        id="delivered-orders",
    ),
    pytest.param(
        "Show processing orders and their amounts.",
        "text_to_sql",
        id="processing-orders",
    ),
    pytest.param(
        "What is the warranty policy for Dell Inspiron 15?",
        "web_research",
        id="warranty-policy",
    ),
    pytest.param(
        "Summarize the return policy.",
        "web_research",
        id="return-policy",
    ),
    pytest.param(
        "Explain the refund process.",
        "web_research",
        id="refund-process",
    ),
    pytest.param(
        "Find the laptop manual guidance.",
        "web_research",
        id="laptop-manual",
    ),
    pytest.param(
        "What does the shipping policy say?",
        "web_research",
        id="shipping-policy",
    ),
    pytest.param(
        "Research laptop competitor trends.",
        "web_research",
        id="laptop-competitors",
    ),
    pytest.param(
        "Analyze smartphone market trends.",
        "web_research",
        id="smartphone-market",
    ),
    pytest.param(
        "Prepare printer competitor research.",
        "web_research",
        id="printer-competitors",
    ),
    pytest.param(
        "Identify smartwatch market opportunities.",
        "web_research",
        id="smartwatch-market",
    ),
    pytest.param(
        "Assess headphone competitor risks.",
        "web_research",
        id="headphone-competitors",
    ),
]


@pytest.fixture(scope="session")
def assistant(tmp_path_factory: pytest.TempPathFactory) -> ResearchAssistant:
    runtime_path = tmp_path_factory.mktemp("milestone3-runtime")
    approval_path = runtime_path / "approval_queue.json"
    return ResearchAssistant(
        workspace_root=WORKSPACE_ROOT,
        database_path=runtime_path / "sales.db",
        memory_path=runtime_path / "memory.db",
        approval_path=approval_path,
        log_path=runtime_path / "events.jsonl",
        use_llm=False,
    )


@pytest.mark.parametrize(("query", "expected_tool"), SYNTHETIC_SCENARIOS)
def test_synthetic_end_to_end_routing(
    assistant: ResearchAssistant,
    query: str,
    expected_tool: str,
) -> None:
    assistant.approval_gate.set_decision(ApprovalUpdate(decision="PASS"))
    response = assistant.run(query, thread_id=f"scenario-{expected_tool}-{query[:12]}")

    assert response.status == "approved"
    assert response.route_history == [
        "supervisor",
        "researcher",
        "writer",
        "approval",
        "finalize",
    ]
    assert expected_tool in response.tools_used
    assert response.report is not None
    assert "## Executive Summary" in response.report
    assert "## Key Findings" in response.report
    assert "## Recommendations" in response.report
    assert "Approved by queue-reviewer" in response.report


def test_sql_validator_rejects_destructive_and_multi_statement_sql(
    assistant: ResearchAssistant,
) -> None:
    destructive = assistant.sql_tool.validate_sql("DROP TABLE sales")
    multiple = assistant.sql_tool.validate_sql(
        "SELECT * FROM sales; DELETE FROM sales"
    )
    internal_table = assistant.sql_tool.validate_sql(
        "SELECT * FROM sqlite_master"
    )

    assert not destructive.valid
    assert not multiple.valid
    assert not internal_table.valid


def test_sql_validation_loop_repairs_unsafe_candidate(
    assistant: ResearchAssistant,
) -> None:
    result = assistant.sql_tool.run(
        TextToSQLInput(
            question="Show revenue by region.",
            candidate_sql="DROP TABLE sales",
        )
    )

    assert result.repaired
    assert len(result.validation_attempts) == 2
    assert not result.validation_attempts[0].valid
    assert result.validation_attempts[1].valid
    assert result.rows


def test_sql_limit_is_capped_at_100(assistant: ResearchAssistant) -> None:
    validation = assistant.sql_tool.validate_sql(
        "SELECT * FROM sales LIMIT 10000"
    )

    assert validation.valid
    assert validation.normalized_sql is not None
    assert "LIMIT 100" in validation.normalized_sql


def test_text_to_sql_honors_requested_result_count(
    assistant: ResearchAssistant,
) -> None:
    result = assistant.sql_tool.run(
        TextToSQLInput(
            question="Which three products generated the highest revenue?"
        )
    )

    assert len(result.rows) == 3
    assert "LIMIT 3" in result.sql


def test_database_bootstrap_creates_expected_tables(tmp_path: Path) -> None:
    database_path = bootstrap_enterprise_database(
        WORKSPACE_ROOT,
        tmp_path / "enterprise.db",
    )
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {"sales", "orders"} <= tables


def test_queued_fail_withholds_report(assistant: ResearchAssistant) -> None:
    assistant.approval_gate.set_decision(ApprovalUpdate(decision="FAIL"))
    response = assistant.run(
        "Summarize the refund policy.",
        thread_id="hitl-rejection",
    )

    assert response.status == "rejected"
    assert response.approval.decision == "FAIL"
    assert response.route_history[-1] == "reject"
    assert response.report is None


def test_invalid_queue_file_is_rejected(assistant: ResearchAssistant) -> None:
    assistant.approval_queue_path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        assistant.run(
            "Summarize the return policy.",
            thread_id="invalid-queue",
        )
    assistant.approval_queue_path.write_text("[]\n", encoding="utf-8")


def test_memory_persists_and_semantically_recalls(tmp_path: Path) -> None:
    memory_path = tmp_path / "persistent-memory.db"
    first_store = SQLiteMemoryStore(memory_path)
    first_store.store(
        MemoryWriteInput(
            thread_id="memory-session",
            kind="semantic",
            text="Samsung Galaxy S24 led product revenue in the sales analysis.",
        )
    )

    reopened_store = SQLiteMemoryStore(memory_path)
    recalled = reopened_store.recall(
        MemorySearchInput(
            query="Which Samsung product led revenue?",
            thread_id="memory-session",
        )
    )

    assert recalled.records
    assert "Samsung Galaxy S24" in recalled.records[0].text
    assert recalled.records[0].score > 0


def test_supervisor_routes_memory_only_request_to_writer(
    assistant: ResearchAssistant,
) -> None:
    thread_id = "memory-routing"
    assistant.approval_gate.set_decision(ApprovalUpdate(decision="PASS"))
    assistant.approval_gate.set_decision(ApprovalUpdate(decision="PASS"))
    assistant.run("Show revenue by region.", thread_id=thread_id)
    recalled_response = assistant.run(
        "Recall our previous report.",
        thread_id=thread_id,
    )

    assert recalled_response.route_history == [
        "supervisor",
        "writer",
        "approval",
        "finalize",
    ]
    assert recalled_response.tools_used == []
    assert recalled_response.report is not None
    assert "Persistent conversation memory" in recalled_response.report


def test_stream_emits_intermediate_and_final_events(
    assistant: ResearchAssistant,
) -> None:
    assistant.approval_gate.set_decision(ApprovalUpdate(decision="PASS"))
    events = list(
        assistant.stream(
            "Show revenue by region.",
            thread_id="stream-events",
        )
    )

    assert [event.node for event in events[:-1]] == [
        "supervisor",
        "researcher",
        "writer",
        "approval",
        "finalize",
    ]
    assert events[-1].event == "workflow_completed"
    assert events[-1].status == "approved"


def test_structured_json_log_is_parseable(assistant: ResearchAssistant) -> None:
    assistant.approval_gate.set_decision(ApprovalUpdate(decision="PASS"))
    assistant.run("Summarize the return policy.", thread_id="json-log")
    file_handlers = [
        handler
        for handler in assistant.logger.handlers
        if hasattr(handler, "baseFilename")
    ]
    assert file_handlers

    log_path = Path(file_handlers[0].baseFilename)
    records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert records
    assert all("event" in record and "details" in record for record in records)


@pytest.fixture()
def api_client(assistant: ResearchAssistant) -> TestClient:
    assistant.approval_queue_path.write_text("[]\n", encoding="utf-8")
    return TestClient(create_app(assistant=assistant))


def test_fastapi_health_and_approval_endpoints(api_client: TestClient) -> None:
    health_response = api_client.get("/health")
    approval_response = api_client.post(
        "/approval",
        json={"decision": "PASS"},
    )

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert "supervisor" in health_response.json()["graph_nodes"]
    assert approval_response.status_code == 200
    assert approval_response.json()["decision"] == "PASS"


def test_fastapi_research_endpoint(api_client: TestClient) -> None:
    api_client.post("/approval", json={"decision": "PASS"})
    response = api_client.post(
        "/research",
        json={
            "query": "Which products generated the highest revenue?",
            "thread_id": "api-research",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert "text_to_sql" in body["tools_used"]
    assert body["report"] is not None


def test_fastapi_sse_stream(api_client: TestClient) -> None:
    api_client.post("/approval", json={"decision": "PASS"})
    response = api_client.post(
        "/research/stream",
        json={
            "query": "Summarize the laptop warranty policy.",
            "thread_id": "api-stream",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: node_completed" in response.text
    assert "event: workflow_completed" in response.text


def test_fastapi_fail_decision_withholds_report(api_client: TestClient) -> None:
    api_client.post("/approval", json={"decision": "FAIL"})
    response = api_client.post(
        "/research",
        json={
            "query": "Summarize the return policy.",
            "thread_id": "api-reject",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["report"] is None


def test_fastapi_rejects_invalid_approval_value(api_client: TestClient) -> None:
    response = api_client.post("/approval", json={"decision": "MAYBE"})

    assert response.status_code == 422
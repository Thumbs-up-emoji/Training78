"""FastAPI surface for the Milestone-4 Enterprise AI Governance Platform.

Exposes:

- ``GET /health``                 -- service heartbeat + registered MCP tools/agents.
- ``POST /governance/query``      -- guardrail -> route -> guardrail-filter governed query.
- ``POST /guardrails/check``      -- run the AI Safety Tool against arbitrary text.
- ``POST /guardrails/run``        -- run the guardrail dataset regression suite.
- ``POST /evaluate/run``          -- run the LLM Evaluation Tool (Promptfoo/RAGAS/hallucination).
- ``GET  /mcp/tools``             -- MCP tool discovery.
- ``POST /mcp/rpc``               -- generic MCP JSON-RPC 2.0 endpoint (initialize/tools.list/tools.call/context).
- ``GET  /a2a/agents``            -- A2A capability registry listing.
- ``POST /a2a/route``             -- A2A message routing to a capability-matched agent.
- ``POST /research`` / ``POST /research/stream`` / ``POST /approval`` -- the Milestone-3 engine, unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core import ApprovalUpdate, ResearchResponse
from app.governance.a2a import AgentCard, A2AEnvelope
from app.governance.evaluation import EvaluationReport
from app.governance.guardrails import GuardrailSuiteReport, GuardrailVerdict
from app.governance.mcp import MCPRpcRequest, MCPRpcResponse, MCPToolDefinition
from app.governance.platform import GovernancePlatform, GovernanceQueryResponse


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GovernanceQueryRequest(APIModel):
    query: str = Field(min_length=3)
    thread_id: str = Field(default_factory=lambda: f"governance-{uuid4()}")


class GuardrailCheckRequest(APIModel):
    text: str = Field(min_length=1)


class A2ARouteRequest(APIModel):
    capability: str = Field(min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)
    sender: str = "RouterAgent"
    conversation_id: str | None = None


class ApprovalRequestBody(APIModel):
    decision: str = Field(pattern=r"^(PASS|FAIL)$")


class ApprovalFileResponse(APIModel):
    decision: str
    approval_queue: str
    queue_depth: int


class HealthResponse(APIModel):
    status: str
    graph_nodes: list[str]
    mcp_server: str
    mcp_tools: list[str]
    a2a_agents: list[str]
    approval_queue: str
    queue_depth: int


class ResearchRequest(APIModel):
    query: str = Field(min_length=3)
    thread_id: str = Field(default_factory=lambda: f"api-{uuid4()}")


def create_app(
    workspace_root: Path | str | None = None,
    platform: GovernancePlatform | None = None,
) -> FastAPI:
    load_dotenv()
    root = Path(workspace_root or Path(__file__).parents[1]).resolve()
    governance_platform = platform or GovernancePlatform(workspace_root=root)
    research_assistant = governance_platform.research_assistant

    application = FastAPI(
        title="Milestone 4 Enterprise AI Governance Platform API",
        version="1.0.0",
        description=(
            "LLM evaluation, AI safety guardrails, MCP tool serving, A2A messaging, "
            "and the Milestone-3 multi-agent research engine (RAG + Text-to-SQL + HITL)."
        ),
    )
    application.state.governance_platform = governance_platform

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            graph_nodes=["supervisor", "researcher", "writer", "approval", "finalize", "reject"],
            mcp_server=governance_platform.mcp_server.name,
            mcp_tools=[tool.name for tool in governance_platform.mcp_server.list_tools()],
            a2a_agents=[agent.name for agent in governance_platform.agent_registry.all_agents()],
            approval_queue=str(research_assistant.approval_queue_path),
            queue_depth=research_assistant.approval_gate.pending_count(),
        )

    @application.post("/governance/query", response_model=GovernanceQueryResponse)
    def governance_query(request: GovernanceQueryRequest) -> GovernanceQueryResponse:
        try:
            return governance_platform.handle_request(query=request.query, thread_id=request.thread_id)
        except (OSError, ValueError, RuntimeError, LookupError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/guardrails/check", response_model=GuardrailVerdict)
    def guardrails_check(request: GuardrailCheckRequest) -> GuardrailVerdict:
        return governance_platform.guardrails.check_prompt(request.text)

    @application.post("/guardrails/run", response_model=GuardrailSuiteReport)
    def guardrails_run() -> GuardrailSuiteReport:
        return governance_platform.run_guardrail_suite()

    @application.post("/evaluate/run", response_model=EvaluationReport)
    def evaluate_run() -> EvaluationReport:
        return governance_platform.run_evaluation_suite()

    @application.get("/mcp/tools", response_model=list[MCPToolDefinition])
    def mcp_tools() -> list[MCPToolDefinition]:
        return governance_platform.mcp_server.list_tools()

    @application.post("/mcp/rpc", response_model=MCPRpcResponse)
    def mcp_rpc(request: MCPRpcRequest) -> MCPRpcResponse:
        return governance_platform.mcp_server.handle_rpc(request)

    @application.get("/a2a/agents", response_model=list[AgentCard])
    def a2a_agents() -> list[AgentCard]:
        return governance_platform.agent_registry.all_agents()

    @application.post("/a2a/route", response_model=A2AEnvelope)
    def a2a_route(request: A2ARouteRequest) -> A2AEnvelope:
        try:
            return governance_platform.message_router.route(
                capability=request.capability,
                content=request.content,
                sender=request.sender,
                conversation_id=request.conversation_id,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.post("/approval", response_model=ApprovalFileResponse)
    def update_approval(body: ApprovalRequestBody) -> ApprovalFileResponse:
        update = ApprovalUpdate(decision=body.decision)
        research_assistant.approval_gate.enqueue_decision(update, source="governance-api")
        return ApprovalFileResponse(
            decision=update.decision,
            approval_queue=str(research_assistant.approval_queue_path),
            queue_depth=research_assistant.approval_gate.pending_count(),
        )

    @application.post("/research", response_model=ResearchResponse)
    def research(request: ResearchRequest) -> ResearchResponse:
        try:
            return research_assistant.run(query=request.query, thread_id=request.thread_id)
        except (OSError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/research/stream")
    def research_stream(request: ResearchRequest) -> StreamingResponse:
        def event_source() -> Iterator[str]:
            try:
                for event in research_assistant.stream(query=request.query, thread_id=request.thread_id):
                    yield f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
            except (OSError, ValueError, RuntimeError) as error:
                yield f"event: error\ndata: {str(error)}\n\n"

        return StreamingResponse(event_source(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    return application


app = create_app()

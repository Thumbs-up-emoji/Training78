"""GovernancePlatform: the Milestone-4 Enterprise AI Governance Platform
orchestrator. Wraps the Milestone-3 ``ResearchAssistant`` engine with:

- inbound/outbound AI Safety Guardrails (prompt injection, jailbreak, PII),
- an MCP server exposing ``rag``, ``text2sql``, ``evaluation``, and
  ``guardrails`` tools (per ``Milestone4_Datasets/mcp_config.json``),
- an A2A capability registry and message router wired to ``RouterAgent``,
  ``ResearchAgent``, ``SQLAgent``, and ``EvaluationAgent`` (per
  ``Milestone4_Datasets/agent_registry.json``),
- the LLM Evaluation Tool and Eval-Driven Development regression gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core import ResearchAssistant, configure_json_logging, log_event
from app.governance.a2a import CapabilityRegistry, MessageRouter
from app.governance.evaluation import EvaluationEngine, EvaluationReport, evaluate_regression_gate
from app.governance.guardrails import GuardrailEngine, GuardrailSuiteReport, GuardrailVerdict
from app.governance.mcp import MCPClient, MCPServer, MCPToolDefinition
from app.governance.rag_sql import (
    GovernanceKnowledgeBase,
    GovernanceSQLInput,
    GovernanceTextToSQLTool,
    bootstrap_governance_database,
)


class GovernanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GovernanceQueryResponse(GovernanceModel):
    query: str
    thread_id: str
    inbound_guardrail: GuardrailVerdict
    outbound_guardrail: GuardrailVerdict | None = None
    routed_capability: str | None = None
    routed_agent: str | None = None
    blocked: bool
    answer: str | None
    research_response: dict[str, Any] | None = None


class GovernancePlatform:
    """Top-level facade tying the research engine, guardrails, MCP, A2A, and
    evaluation subsystems together into one governed request/response flow.
    """

    def __init__(
        self,
        workspace_root: Path | str = Path.cwd(),
        datasets_root: Path | str | None = None,
        knowledge_base_root: Path | str | None = None,
        use_llm: bool | None = None,
        refresh_governance_database: bool = False,
        database_path: Path | str | None = None,
        memory_path: Path | str | None = None,
        approval_path: Path | str | None = None,
        log_path: Path | str | None = None,
        governance_database_path: Path | str | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.datasets_root = Path(datasets_root or self.workspace_root / "Milestone4_Datasets").resolve()
        self.knowledge_base_root = Path(
            knowledge_base_root or self.workspace_root / "Milestone4_Knowledge_Base"
        ).resolve()

        artifacts_dir = self.workspace_root / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = Path(log_path).resolve() if log_path else artifacts_dir / "milestone4.jsonl"
        self.logger = configure_json_logging(self.log_path, logger_name="milestone4_governance")

        # Milestone-3 core engine, reused as-is (supervisor/researcher/writer/HITL).
        # database_path/memory_path/approval_path allow tests to isolate runtime state
        # from the real workspace artifacts/ directory, matching the Milestone-3 fixture pattern.
        self.research_assistant = ResearchAssistant(
            workspace_root=self.workspace_root,
            database_path=database_path,
            memory_path=memory_path,
            approval_path=approval_path,
            log_path=self.log_path,
            use_llm=use_llm,
        )

        # AI Safety Tool
        self.guardrails = GuardrailEngine(logger=self.logger)

        # LLM Evaluation Tool
        self.evaluation_engine = EvaluationEngine(
            dataset_path=self.datasets_root / "evaluation_dataset.json",
            logger=self.logger,
        )

        # Governance RAG + secure Text-to-SQL over the new Milestone-4 datasets.
        self.governance_db_path = (
            Path(governance_database_path).resolve() if governance_database_path else artifacts_dir / "governance.db"
        )
        bootstrap_governance_database(
            self.datasets_root,
            self.governance_db_path,
            refresh=refresh_governance_database,
        )
        self.governance_sql_tool = GovernanceTextToSQLTool(self.governance_db_path, logger=self.logger)
        self.governance_kb = GovernanceKnowledgeBase(self.knowledge_base_root)

        # MCP Tool: server registers rag/text2sql/evaluation/guardrails per mcp_config.json.
        self.mcp_server = MCPServer.from_config(self.datasets_root / "mcp_config.json", logger=self.logger)
        self._register_mcp_tools()
        self.mcp_client = MCPClient(server=self.mcp_server)

        # A2A Tool: capability registry + message router per agent_registry.json.
        self.agent_registry = CapabilityRegistry.from_config(self.datasets_root / "agent_registry.json")
        self.message_router = MessageRouter(self.agent_registry, logger=self.logger)
        self._register_a2a_handlers()

    def _register_mcp_tools(self) -> None:
        self.mcp_server.register_tool(
            MCPToolDefinition(
                name="rag",
                description="Search the Milestone-4 governance knowledge base.",
                input_schema={"query": "string", "top_k": "integer"},
            ),
            handler=lambda args: self.governance_kb.search(args["query"], top_k=args.get("top_k", 5)),
        )
        self.mcp_server.register_tool(
            MCPToolDefinition(
                name="text2sql",
                description="Run secure, read-only SQL over the governance datasets.",
                input_schema={"question": "string"},
            ),
            handler=lambda args: self.governance_sql_tool.run(
                GovernanceSQLInput(question=args["question"])
            ).model_dump(),
        )
        self.mcp_server.register_tool(
            MCPToolDefinition(
                name="evaluation",
                description="Run the LLM evaluation suite (Promptfoo/RAGAS/hallucination).",
                input_schema={},
            ),
            handler=lambda args: self.evaluation_engine.run().model_dump(),
        )
        self.mcp_server.register_tool(
            MCPToolDefinition(
                name="guardrails",
                description="Check text against the AI safety guardrails.",
                input_schema={"text": "string"},
            ),
            handler=lambda args: self.guardrails.check_prompt(args["text"]).model_dump(),
        )

    def _register_a2a_handlers(self) -> None:
        self.message_router.register_handler(
            "ResearchAgent",
            lambda message: {"kb_hits": self.governance_kb.search(message.content.get("query", ""), top_k=3)},
        )
        self.message_router.register_handler(
            "SQLAgent",
            lambda message: self.governance_sql_tool.run(
                GovernanceSQLInput(question=message.content.get("question", ""))
            ).model_dump(),
        )

        def _evaluation_handler(message: Any) -> dict[str, Any]:
            del message
            report = self.evaluation_engine.run()
            gate_passed, violations = evaluate_regression_gate(report)
            return {"pass_rate": report.pass_rate, "gate_passed": gate_passed, "violations": violations}

        self.message_router.register_handler("EvaluationAgent", _evaluation_handler)

    @staticmethod
    def _classify_capability(query: str) -> tuple[str, str]:
        lowered = query.lower()
        sql_terms = ("competitor", "market share", "product price", "quarterly", "governance revenue", "governance region")
        rag_terms = ("policy", "policies", "coding standard", "architecture", "prompt librar", "product documentation", "industry report")
        if any(term in lowered for term in sql_terms):
            return "text2sql", "SQLAgent"
        if any(term in lowered for term in rag_terms):
            return "rag", "ResearchAgent"
        return "full_research", "ResearchAssistant"

    @staticmethod
    def _summarize_kb_hits(hits: list[dict[str, Any]]) -> str:
        if not hits:
            return "No governance knowledge-base match found."
        return "\n".join(f"- ({hit['source']} / {hit['section']}) {hit['text']}" for hit in hits)

    @staticmethod
    def _summarize_sql_rows(sql_output: dict[str, Any]) -> str:
        rows = sql_output.get("rows", [])
        if not rows:
            return "No matching governance records found."
        return "\n".join(str(row) for row in rows[:10])

    def handle_request(self, query: str, thread_id: str = "governance-default") -> GovernanceQueryResponse:
        """Guardrail -> route (A2A/MCP) -> guardrail-filter governed request flow."""
        inbound_verdict = self.guardrails.check_prompt(query)
        if inbound_verdict.action == "block":
            log_event(
                self.logger,
                "governance_request_blocked",
                thread_id=thread_id,
                category=inbound_verdict.category,
            )
            return GovernanceQueryResponse(
                query=query,
                thread_id=thread_id,
                inbound_guardrail=inbound_verdict,
                outbound_guardrail=None,
                routed_capability=None,
                routed_agent=None,
                blocked=True,
                answer=None,
                research_response=None,
            )

        sanitized_query = inbound_verdict.sanitized_text
        capability, agent_name = self._classify_capability(sanitized_query)

        research_response: dict[str, Any] | None = None
        if capability == "text2sql":
            envelope = self.message_router.route("text2sql", {"question": sanitized_query}, conversation_id=thread_id)
            answer = self._summarize_sql_rows(envelope.response.content)
        elif capability == "rag":
            envelope = self.message_router.route("rag", {"query": sanitized_query}, conversation_id=thread_id)
            answer = self._summarize_kb_hits(envelope.response.content.get("kb_hits", []))
        else:
            response = self.research_assistant.run(sanitized_query, thread_id=thread_id)
            research_response = response.model_dump()
            answer = response.report or "Report withheld pending human approval."

        outbound_verdict = self.guardrails.filter_response(answer)
        final_answer = outbound_verdict.sanitized_text if outbound_verdict.action != "allow" else answer

        log_event(
            self.logger,
            "governance_request_completed",
            thread_id=thread_id,
            capability=capability,
            agent=agent_name,
            blocked=False,
        )
        return GovernanceQueryResponse(
            query=query,
            thread_id=thread_id,
            inbound_guardrail=inbound_verdict,
            outbound_guardrail=outbound_verdict,
            routed_capability=capability,
            routed_agent=agent_name,
            blocked=False,
            answer=final_answer,
            research_response=research_response,
        )

    def run_evaluation_suite(self) -> EvaluationReport:
        return self.evaluation_engine.run()

    def run_guardrail_suite(self) -> GuardrailSuiteReport:
        return self.guardrails.run_dataset(self.datasets_root / "guardrail_dataset.json")

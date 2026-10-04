"""Milestone-4 Enterprise AI Governance Platform package.

This package extends the Milestone-3 multi-agent research engine (``app.core``)
with the governance capabilities required for Milestone 4:

- ``evaluation``  -- LLM Evaluation Tool (Promptfoo-compatible assertions, RAGAS-style
  metrics, LangSmith tracing hooks, hallucination detection).
- ``guardrails``  -- AI Safety Tool (prompt-injection detection, jailbreak detection,
  PII detection, response filtering).
- ``mcp``         -- Model Context Protocol server and client (tool registration,
  discovery, invocation, per-session context sharing).
- ``a2a``         -- Agent-to-Agent communication (capability registry, agent
  discovery, structured message routing).
- ``rag_sql``     -- Governance-scoped RAG knowledge base and secure Text-to-SQL over
  the Milestone-4 datasets (products, competitors, quarterly_sales).
- ``platform``    -- ``GovernancePlatform`` orchestrator wiring all of the above
  together with the Milestone-3 ``ResearchAssistant``.
"""

from app.governance.a2a import (
    A2AEnvelope,
    A2AMessage,
    AgentCard,
    CapabilityRegistry,
    MessageRouter,
)
from app.governance.evaluation import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationEngine,
    EvaluationReport,
    HallucinationDetector,
    HallucinationVerdict,
    PromptfooEvaluator,
    RagasMetricComputer,
    RagasScores,
    evaluate_regression_gate,
    render_markdown_report,
)
from app.governance.guardrails import (
    GuardrailCaseResult,
    GuardrailDatasetCase,
    GuardrailEngine,
    GuardrailFinding,
    GuardrailSuiteReport,
    GuardrailVerdict,
    JailbreakDetector,
    PIIDetector,
    PromptInjectionDetector,
)
from app.governance.mcp import (
    MCPClient,
    MCPRpcRequest,
    MCPRpcResponse,
    MCPServer,
    MCPSession,
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolDefinition,
)
from app.governance.platform import GovernancePlatform, GovernanceQueryResponse
from app.governance.rag_sql import (
    GovernanceKnowledgeBase,
    GovernanceSQLInput,
    GovernanceTextToSQLTool,
    bootstrap_governance_database,
)

__all__ = [
    "A2AEnvelope",
    "A2AMessage",
    "AgentCard",
    "CapabilityRegistry",
    "EvaluationCase",
    "EvaluationCaseResult",
    "EvaluationEngine",
    "EvaluationReport",
    "GovernanceKnowledgeBase",
    "GovernancePlatform",
    "GovernanceQueryResponse",
    "GovernanceSQLInput",
    "GovernanceTextToSQLTool",
    "GuardrailCaseResult",
    "GuardrailDatasetCase",
    "GuardrailEngine",
    "GuardrailFinding",
    "GuardrailSuiteReport",
    "GuardrailVerdict",
    "HallucinationDetector",
    "HallucinationVerdict",
    "JailbreakDetector",
    "MCPClient",
    "MCPRpcRequest",
    "MCPRpcResponse",
    "MCPServer",
    "MCPSession",
    "MCPToolCallRequest",
    "MCPToolCallResult",
    "MCPToolDefinition",
    "MessageRouter",
    "PIIDetector",
    "PromptInjectionDetector",
    "PromptfooEvaluator",
    "RagasMetricComputer",
    "RagasScores",
    "bootstrap_governance_database",
    "evaluate_regression_gate",
    "render_markdown_report",
]

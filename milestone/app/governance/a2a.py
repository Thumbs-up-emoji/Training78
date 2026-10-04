"""Agent-to-Agent (A2A) Tool: agent discovery, capability registry, and
structured message routing between the enterprise agents defined in
``Milestone4_Datasets/agent_registry.json`` (RouterAgent, ResearchAgent,
SQLAgent, EvaluationAgent).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core import configure_json_logging, log_event

Performative = Literal["request", "inform", "failure", "refuse"]
AgentStatus = Literal["online", "offline"]


class A2AModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentCard(A2AModel):
    """Advertises an agent's identity and capabilities, per the A2A capability registry."""

    name: str
    capabilities: list[str]
    status: AgentStatus = "online"


class CapabilityRegistry:
    """Capability Registry: tracks known agents and supports discovery by capability."""

    def __init__(self, agents: list[AgentCard] | None = None):
        self._agents: dict[str, AgentCard] = {agent.name: agent for agent in (agents or [])}

    @classmethod
    def from_config(cls, config_path: Path | str) -> CapabilityRegistry:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
        agents = [AgentCard.model_validate(agent) for agent in payload["agents"]]
        return cls(agents)

    def register(self, agent: AgentCard) -> None:
        self._agents[agent.name] = agent

    def discover(self, capability: str) -> list[AgentCard]:
        """Agent Discovery: return online agents that advertise the requested capability."""
        return [agent for agent in self._agents.values() if capability in agent.capabilities and agent.status == "online"]

    def all_agents(self) -> list[AgentCard]:
        return list(self._agents.values())

    def get(self, name: str) -> AgentCard | None:
        return self._agents.get(name)

    def set_status(self, name: str, status: AgentStatus) -> None:
        if name in self._agents:
            self._agents[name] = self._agents[name].model_copy(update={"status": status})


class A2AMessage(A2AModel):
    """A structured FIPA-ACL-inspired agent message."""

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    sender: str
    receiver: str
    performative: Performative
    capability: str
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class A2AEnvelope(A2AModel):
    request: A2AMessage
    response: A2AMessage


class MessageRouter:
    """Message Routing: dispatches a capability-tagged task to the appropriate
    agent handler (discovered via the capability registry) and returns a
    structured request/response envelope, logging every hop.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        logger: logging.Logger | None = None,
        log_path: Path | None = None,
    ):
        self.registry = registry
        self.logger = logger or configure_json_logging(log_path, logger_name="milestone4_governance")
        self._handlers: dict[str, Callable[[A2AMessage], dict[str, Any]]] = {}

    def register_handler(self, agent_name: str, handler: Callable[[A2AMessage], dict[str, Any]]) -> None:
        self._handlers[agent_name] = handler

    def route(
        self,
        capability: str,
        content: dict[str, Any],
        sender: str = "RouterAgent",
        conversation_id: str | None = None,
    ) -> A2AEnvelope:
        conversation_id = conversation_id or str(uuid4())
        candidates = self.registry.discover(capability)
        if not candidates:
            raise LookupError(f"No online agent advertises capability '{capability}'.")
        receiver = candidates[0]

        request_message = A2AMessage(
            conversation_id=conversation_id,
            sender=sender,
            receiver=receiver.name,
            performative="request",
            capability=capability,
            content=content,
        )
        log_event(
            self.logger,
            "a2a_message_sent",
            conversation_id=conversation_id,
            sender=sender,
            receiver=receiver.name,
            capability=capability,
        )

        handler = self._handlers.get(receiver.name)
        if handler is None:
            response_message = A2AMessage(
                conversation_id=conversation_id,
                sender=receiver.name,
                receiver=sender,
                performative="refuse",
                capability=capability,
                content={"reason": "no handler registered for this agent"},
            )
        else:
            try:
                result = handler(request_message)
                response_message = A2AMessage(
                    conversation_id=conversation_id,
                    sender=receiver.name,
                    receiver=sender,
                    performative="inform",
                    capability=capability,
                    content=result,
                )
            except Exception as error:  # noqa: BLE001 - surfaced as a structured A2A failure message
                response_message = A2AMessage(
                    conversation_id=conversation_id,
                    sender=receiver.name,
                    receiver=sender,
                    performative="failure",
                    capability=capability,
                    content={"error": str(error)},
                )

        log_event(
            self.logger,
            "a2a_message_received",
            conversation_id=conversation_id,
            sender=response_message.sender,
            receiver=sender,
            performative=response_message.performative,
        )
        return A2AEnvelope(request=request_message, response=response_message)

"""Model Context Protocol (MCP) Tool: an MCP server and client implementing tool
registration, tool discovery, tool invocation, and per-session context sharing.

Calls are dispatched through a JSON-RPC 2.0-shaped envelope (:class:`MCPRpcRequest`
/ :class:`MCPRpcResponse`) mirroring the real Model Context Protocol wire format
(``initialize``, ``tools/list``, ``tools/call``), plus governance-specific
``context/get`` and ``context/set`` methods for cross-call context sharing. The
same envelope works in-process (:class:`MCPClient` wrapping an :class:`MCPServer`
directly) or over HTTP (``MCPClient(base_url=...)`` posting to the
``/mcp/rpc`` FastAPI route in :mod:`app.governance_api`).
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

MCPRpcMethod = Literal["initialize", "tools/list", "tools/call", "context/get", "context/set"]


class MCPModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MCPToolDefinition(MCPModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPToolCallRequest(MCPModel):
    session_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolCallResult(MCPModel):
    call_id: str
    tool: str
    session_id: str
    success: bool
    output: Any = None
    error: str | None = None


class MCPSession(MCPModel):
    session_id: str
    created_at: str
    context: dict[str, Any] = Field(default_factory=dict)


class MCPRpcRequest(MCPModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid4()))
    method: MCPRpcMethod
    params: dict[str, Any] = Field(default_factory=dict)


class MCPRpcResponse(MCPModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class MCPServer:
    """MCP server: registers tools, advertises them for discovery, executes
    tool calls, and maintains a per-session context store that tool handlers
    and callers can read and write across multiple calls (context sharing).
    """

    def __init__(
        self,
        name: str,
        version: str,
        logger: logging.Logger | None = None,
        log_path: Path | None = None,
    ):
        self.name = name
        self.version = version
        self.logger = logger or configure_json_logging(log_path, logger_name="milestone4_governance")
        self._tools: dict[str, MCPToolDefinition] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._sessions: dict[str, MCPSession] = {}

    @classmethod
    def from_config(cls, config_path: Path | str, **kwargs: Any) -> MCPServer:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return cls(name=payload["server_name"], version=str(payload["version"]), **kwargs)

    def register_tool(
        self,
        definition: MCPToolDefinition,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler
        log_event(self.logger, "mcp_tool_registered", server=self.name, tool=definition.name)

    def open_session(self) -> MCPSession:
        session = MCPSession(session_id=str(uuid4()), created_at=datetime.now(timezone.utc).isoformat())
        self._sessions[session.session_id] = session
        log_event(self.logger, "mcp_session_opened", server=self.name, session_id=session.session_id)
        return session

    def list_tools(self) -> list[MCPToolDefinition]:
        log_event(self.logger, "mcp_tool_discovery", server=self.name, tool_count=len(self._tools))
        return list(self._tools.values())

    def _require_session(self, session_id: str) -> MCPSession:
        if session_id not in self._sessions:
            raise KeyError(f"Unknown MCP session: {session_id}")
        return self._sessions[session_id]

    def get_context(self, session_id: str) -> dict[str, Any]:
        return dict(self._require_session(session_id).context)

    def set_context(self, session_id: str, key: str, value: Any) -> None:
        session = self._require_session(session_id)
        session.context[key] = value
        log_event(self.logger, "mcp_context_shared", server=self.name, session_id=session_id, key=key)

    def call_tool(self, request: MCPToolCallRequest) -> MCPToolCallResult:
        call_id = str(uuid4())
        if request.tool not in self._handlers:
            log_event(
                self.logger, "mcp_tool_call_failed", server=self.name, tool=request.tool, reason="unknown_tool"
            )
            return MCPToolCallResult(
                call_id=call_id,
                tool=request.tool,
                session_id=request.session_id,
                success=False,
                error=f"Unknown tool: {request.tool}",
            )

        session = self._require_session(request.session_id)
        try:
            output = self._handlers[request.tool](request.arguments)
            session.context[f"last_result::{request.tool}"] = output
            log_event(
                self.logger,
                "mcp_tool_call",
                server=self.name,
                tool=request.tool,
                session_id=request.session_id,
                success=True,
            )
            return MCPToolCallResult(
                call_id=call_id, tool=request.tool, session_id=request.session_id, success=True, output=output
            )
        except Exception as error:  # noqa: BLE001 - surfaced to caller as a structured MCP error
            log_event(
                self.logger,
                "mcp_tool_call",
                server=self.name,
                tool=request.tool,
                session_id=request.session_id,
                success=False,
                error=str(error),
            )
            return MCPToolCallResult(
                call_id=call_id, tool=request.tool, session_id=request.session_id, success=False, error=str(error)
            )

    def handle_rpc(self, request: MCPRpcRequest) -> MCPRpcResponse:
        try:
            if request.method == "initialize":
                session = self.open_session()
                return MCPRpcResponse(
                    id=request.id,
                    result={"server": self.name, "version": self.version, "session_id": session.session_id},
                )
            if request.method == "tools/list":
                return MCPRpcResponse(id=request.id, result={"tools": [t.model_dump() for t in self.list_tools()]})
            if request.method == "tools/call":
                call_request = MCPToolCallRequest.model_validate(request.params)
                result = self.call_tool(call_request)
                return MCPRpcResponse(id=request.id, result=result.model_dump())
            if request.method == "context/get":
                session_id = request.params["session_id"]
                return MCPRpcResponse(id=request.id, result={"context": self.get_context(session_id)})
            if request.method == "context/set":
                self.set_context(request.params["session_id"], request.params["key"], request.params["value"])
                return MCPRpcResponse(id=request.id, result={"ok": True})
            raise ValueError(f"Unsupported MCP method: {request.method}")
        except Exception as error:  # noqa: BLE001 - JSON-RPC error envelope
            return MCPRpcResponse(id=request.id, error={"code": -32000, "message": str(error)})


class MCPClient:
    """MCP client performing initialize -> discover -> call -> context flows.

    Wrap an in-process :class:`MCPServer` for zero-transport calls (used inside
    :class:`~app.governance.platform.GovernancePlatform`), or pass ``base_url``
    to talk to a server exposed over HTTP via ``POST {base_url}/mcp/rpc``.
    """

    def __init__(self, server: MCPServer | None = None, base_url: str | None = None):
        if server is None and base_url is None:
            raise ValueError("MCPClient requires either an in-process server or a base_url.")
        self.server = server
        self.base_url = base_url.rstrip("/") if base_url else None
        self.session_id: str | None = None

    def _dispatch(self, request: MCPRpcRequest) -> MCPRpcResponse:
        if self.server is not None:
            return self.server.handle_rpc(request)

        import httpx

        response = httpx.post(f"{self.base_url}/mcp/rpc", json=request.model_dump(), timeout=20.0)
        response.raise_for_status()
        return MCPRpcResponse.model_validate(response.json())

    def initialize(self) -> str:
        response = self._dispatch(MCPRpcRequest(method="initialize"))
        if response.error:
            raise RuntimeError(response.error["message"])
        self.session_id = response.result["session_id"]
        return self.session_id

    def discover_tools(self) -> list[MCPToolDefinition]:
        response = self._dispatch(MCPRpcRequest(method="tools/list"))
        if response.error:
            raise RuntimeError(response.error["message"])
        return [MCPToolDefinition.model_validate(tool) for tool in response.result["tools"]]

    def call_tool(self, tool: str, arguments: dict[str, Any] | None = None) -> MCPToolCallResult:
        if self.session_id is None:
            self.initialize()
        params = MCPToolCallRequest(session_id=self.session_id, tool=tool, arguments=arguments or {}).model_dump()
        response = self._dispatch(MCPRpcRequest(method="tools/call", params=params))
        if response.error:
            raise RuntimeError(response.error["message"])
        return MCPToolCallResult.model_validate(response.result)

    def share_context(self, key: str, value: Any) -> None:
        if self.session_id is None:
            self.initialize()
        response = self._dispatch(
            MCPRpcRequest(method="context/set", params={"session_id": self.session_id, "key": key, "value": value})
        )
        if response.error:
            raise RuntimeError(response.error["message"])

    def get_context(self) -> dict[str, Any]:
        if self.session_id is None:
            self.initialize()
        response = self._dispatch(MCPRpcRequest(method="context/get", params={"session_id": self.session_id}))
        if response.error:
            raise RuntimeError(response.error["message"])
        return response.result["context"]

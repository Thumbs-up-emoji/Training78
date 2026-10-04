"""CLI for the Milestone-4 Enterprise AI Governance Platform.

Subcommands:

- ``query``            -- governed request (guardrails -> A2A/MCP routing -> guardrails).
- ``evaluate``          -- run the LLM Evaluation Tool and print/save the report.
- ``guardrail-check``   -- check a single prompt/response against the AI Safety Tool.
- ``guardrail-run``     -- run the guardrail dataset regression suite.
- ``mcp-list-tools``    -- MCP tool discovery.
- ``mcp-call``          -- call an MCP tool by name with JSON arguments.
- ``a2a-list-agents``   -- list the A2A capability registry.
- ``a2a-route``         -- route a capability-tagged message to an agent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from app.governance.platform import GovernancePlatform


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Milestone 4 Enterprise AI Governance Platform CLI.")
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    query_parser = subparsers.add_parser("query", help="Run a governed query through guardrails and routing.")
    query_parser.add_argument("--text", required=True)
    query_parser.add_argument("--thread-id", default="cli-governance-session")
    query_parser.add_argument("--decision", choices=("PASS", "FAIL"), help="Optionally enqueue an approval decision first.")

    evaluate_parser = subparsers.add_parser("evaluate", help="Run the LLM evaluation suite.")
    evaluate_parser.add_argument("--json-out", type=Path, default=None)
    evaluate_parser.add_argument("--markdown-out", type=Path, default=None)

    guardrail_check_parser = subparsers.add_parser("guardrail-check", help="Check text against the AI safety guardrails.")
    guardrail_check_parser.add_argument("--text", required=True)

    subparsers.add_parser("guardrail-run", help="Run the guardrail dataset regression suite.")
    subparsers.add_parser("mcp-list-tools", help="List MCP tools available for discovery.")

    mcp_call_parser = subparsers.add_parser("mcp-call", help="Call an MCP tool by name.")
    mcp_call_parser.add_argument("--tool", required=True)
    mcp_call_parser.add_argument("--arguments", default="{}", help="JSON-encoded tool arguments.")

    subparsers.add_parser("a2a-list-agents", help="List agents in the A2A capability registry.")

    a2a_route_parser = subparsers.add_parser("a2a-route", help="Route a capability-tagged message to an agent.")
    a2a_route_parser.add_argument("--capability", required=True)
    a2a_route_parser.add_argument("--content", default="{}", help="JSON-encoded message content.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    workspace_root = args.workspace_root.resolve()
    platform = GovernancePlatform(workspace_root=workspace_root)

    if args.command == "query":
        if args.decision:
            from app.core import ApprovalUpdate

            platform.research_assistant.approval_gate.enqueue_decision(
                ApprovalUpdate(decision=args.decision), source="governance-cli"
            )
        response = platform.handle_request(query=args.text, thread_id=args.thread_id)
        print(response.model_dump_json(indent=2))

    elif args.command == "evaluate":
        report = platform.run_evaluation_suite()
        print(report.model_dump_json(indent=2))
        if args.json_out or args.markdown_out:
            platform.evaluation_engine.write_report(report, args.json_out, args.markdown_out)

    elif args.command == "guardrail-check":
        verdict = platform.guardrails.check_prompt(args.text)
        print(verdict.model_dump_json(indent=2))

    elif args.command == "guardrail-run":
        report = platform.run_guardrail_suite()
        print(report.model_dump_json(indent=2))

    elif args.command == "mcp-list-tools":
        tools = platform.mcp_server.list_tools()
        print(json.dumps([tool.model_dump() for tool in tools], indent=2))

    elif args.command == "mcp-call":
        arguments = json.loads(args.arguments)
        result = platform.mcp_client.call_tool(args.tool, arguments)
        print(result.model_dump_json(indent=2))

    elif args.command == "a2a-list-agents":
        agents = platform.agent_registry.all_agents()
        print(json.dumps([agent.model_dump() for agent in agents], indent=2))

    elif args.command == "a2a-route":
        content = json.loads(args.content)
        envelope = platform.message_router.route(capability=args.capability, content=content)
        print(envelope.model_dump_json(indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

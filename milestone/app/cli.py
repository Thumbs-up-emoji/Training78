from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from app.core import ApprovalUpdate, ResearchAssistant, ResearchResponse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Milestone 4 multi-agent research assistant (governance-platform core engine)."
    )
    parser.add_argument("--query", help="Research question. Prompts when omitted.")
    parser.add_argument("--thread-id", default="cli-session")
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--approval-queue", type=Path)
    parser.add_argument(
        "--approval-file",
        type=Path,
        help="Deprecated alias for --approval-queue.",
    )
    parser.add_argument(
        "--decision",
        choices=("PASS", "FAIL"),
        help="Optionally enqueue PASS or FAIL before the run.",
    )
    parser.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stream graph-node events as JSON lines.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    workspace_root = args.workspace_root.resolve()
    approval_queue = (
        (args.approval_queue or args.approval_file).resolve()
        if (args.approval_queue or args.approval_file)
        else workspace_root / "artifacts" / "approval_queue.json"
    )
    query = args.query or input("Research request: ").strip()
    if not query:
        raise SystemExit("A non-empty research request is required.")

    assistant = ResearchAssistant(
        workspace_root=workspace_root,
        approval_path=approval_queue,
        log_path=workspace_root / "artifacts" / "milestone4.jsonl",
    )
    if args.decision:
        assistant.approval_gate.enqueue_decision(
            ApprovalUpdate(decision=args.decision),
            source="cli",
        )

    if args.stream:
        response: ResearchResponse | None = None
        for event in assistant.stream(query=query, thread_id=args.thread_id):
            print(event.model_dump_json())
            if event.event == "workflow_completed":
                response = ResearchResponse.model_validate(
                    event.payload["response"]
                )
        if response is None:
            raise RuntimeError("The workflow ended without a final response.")
    else:
        response = assistant.run(query=query, thread_id=args.thread_id)
        print(response.model_dump_json(indent=2))

    if response.report:
        print("\n=== APPROVED REPORT ===\n")
        print(response.report)
    else:
        print("\nReport withheld because the queued approval decision was FAIL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
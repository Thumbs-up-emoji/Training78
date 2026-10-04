"""Wrapper (in ``entrypoints/``) exposing the Milestone-4 Governance Platform
CLI.

Run with: ``python entrypoints/milestone5_governance_cli.py <command> ...``

This is distinct from ``entrypoints/milestone5_cli.py`` (the Milestone-3
research-only CLI, preserved unchanged). This module serves the full
governance CLI: query routing, evaluation, guardrail checks, MCP tool calls,
and A2A agent routing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.governance_cli import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())

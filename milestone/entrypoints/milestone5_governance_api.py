"""Wrapper (in ``entrypoints/``) exposing the Milestone-4 Governance Platform
FastAPI app.

Run with: ``uvicorn entrypoints.milestone5_governance_api:app --reload``

This is distinct from ``entrypoints/milestone5_api.py`` (the Milestone-3
research-only API, preserved unchanged for the regression test suite) and from
``entrypoints/milestone5_production_api.py`` (the new Milestone-5 secured
production API that adds API-key auth and observability on top of this same
governance surface). This module serves the full governance surface: LLM
evaluation, AI safety guardrails, MCP, and A2A, layered on top of the same
research engine.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.governance_api import app, create_app

__all__ = ["app", "create_app"]

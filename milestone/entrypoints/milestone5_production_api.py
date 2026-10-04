"""Wrapper (in ``entrypoints/``) exposing the Milestone-5 secured production
API.

Run with: ``uvicorn entrypoints.milestone5_production_api:app --reload``

This is the new Milestone-5 production surface: API-key authentication
(``X-API-Key``, see ``app/ops/auth.py``), request tracing/cost estimation
(``app/ops/instrumentation.py``), the groundedness guard
(``app/ops/groundedness_guard.py``), and user feedback capture
(``app/ops/feedback.py``) -- all layered on top of the unchanged
``app.governance.platform.GovernancePlatform`` (Milestone 4) which itself
wraps the unchanged Milestone-3 research engine.

Distinct from ``entrypoints/milestone5_api.py`` (Milestone-3 engine only) and
``entrypoints/milestone5_governance_api.py`` (Milestone-4 governance surface,
no auth/observability/groundedness guard).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.production_api import app, create_app

__all__ = ["app", "create_app"]

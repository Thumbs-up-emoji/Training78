"""Milestone 6 secured production API entry point.

Run with ``uvicorn entrypoints.milestone6_production_api:app --host 0.0.0.0 --port 8000``.
This remains an additive wrapper over the unchanged M3/M4 engine and retains
the M5 API-key gateway while requiring a short-lived JWT on protected routes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.production_api import app, create_app

__all__ = ["app", "create_app"]
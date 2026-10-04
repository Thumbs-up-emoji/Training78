"""Wrapper (in ``entrypoints/``) exposing the Milestone-3 research-only FastAPI
app, unchanged, kept for ``tests/test_milestone5_regression.py`` compatibility.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api import app, create_app

__all__ = ["app", "create_app"]

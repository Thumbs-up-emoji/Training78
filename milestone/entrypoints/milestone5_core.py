"""Wrapper (in ``entrypoints/``) exposing the Milestone-3/4 core engine and
governance package (unchanged by Milestone 5 -- see
``entrypoints/milestone5_production_api.py`` and ``app/ops`` for the
Milestone-5 production/observability/security layer).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import *  # noqa: F401,F403
from app.governance import *  # noqa: F401,F403

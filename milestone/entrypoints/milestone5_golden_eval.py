"""Wrapper (in ``entrypoints/``) for the Milestone-5 golden-set evaluation CLI.

Run with::

    python entrypoints/milestone5_golden_eval.py
    python entrypoints/milestone5_golden_eval.py --save-baseline
    python -m app.ops.golden_eval  # equivalent, direct module invocation

See ``app/ops/golden_eval.py`` for the implementation: runs every question in
``golden_set_student.json`` through the live, unchanged
``GovernancePlatform`` (guarded by ``app/ops/groundedness_guard.py``) and
produces a JSON + Markdown report, checked against a saved baseline for
Eval-Driven Development regression detection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ops.golden_eval import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    sys.exit(main())

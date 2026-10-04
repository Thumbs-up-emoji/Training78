"""Wrapper (in ``entrypoints/``) exposing the Milestone-3 research-only CLI,
unchanged.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cli import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())

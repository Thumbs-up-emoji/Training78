"""Documentation completeness check for Milestone 5/6 governance + production.

Verifies that every required documentation artifact exists and is non-empty.
Used by the ``docs`` GitHub Actions workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DOCS: list[str] = [
    "README.md",
    "docs/MILESTONE6_ARCHITECTURE_NOTE.md",
    "docs/PRODUCTION_READINESS_CHECKLIST.md",
    "evals/EVAL_SPECS.md",
    "evals/promptfooconfig.yaml",
    ".github/copilot-instructions.md",
    ".github/skills/rag/SKILL.md",
    ".github/skills/text2sql/SKILL.md",
    ".github/skills/mcp/SKILL.md",
    ".github/skills/evaluation/SKILL.md",
    "Milestone4_Knowledge_Base/Enterprise_Policies.md",
    "Milestone4_Knowledge_Base/Coding_Standards.md",
    "Milestone4_Knowledge_Base/Architecture_Documents.md",
    "Milestone4_Knowledge_Base/Product_Documentation.md",
    "Milestone4_Knowledge_Base/Industry_Reports.md",
    "Milestone4_Knowledge_Base/Prompt_Libraries.md",
]


def main() -> int:
    missing: list[str] = []
    empty: list[str] = []

    for relative_path in REQUIRED_DOCS:
        path = WORKSPACE_ROOT / relative_path
        if not path.exists():
            missing.append(relative_path)
            continue
        if path.stat().st_size == 0:
            empty.append(relative_path)

    if missing or empty:
        if missing:
            print("Missing required documentation files:")
            for item in missing:
                print(f"  - {item}")
        if empty:
            print("Required documentation files are empty:")
            for item in empty:
                print(f"  - {item}")
        return 1

    print(f"All {len(REQUIRED_DOCS)} required documentation files are present and non-empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

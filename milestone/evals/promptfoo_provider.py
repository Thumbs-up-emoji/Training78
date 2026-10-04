#!/usr/bin/env python
"""Promptfoo `exec:` provider for the Milestone-4 evaluation config.

Promptfoo's `exec:` provider type runs this script with the rendered prompt
as the sole command-line argument and treats whatever is printed to stdout
as the model's response. This script is a deterministic, offline stand-in
that mirrors `app.governance.evaluation.EvaluationEngine.default_system_under_test`:
it looks up the matching case in `Milestone4_Datasets/evaluation_dataset.json`
by prompt text and echoes back its `expected_answer`.

Swap this out for a real provider id (e.g. `openai:gpt-4o-mini`) in
`evals/promptfooconfig.yaml` to evaluate a live model instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = WORKSPACE_ROOT / "Milestone4_Datasets" / "evaluation_dataset.json"


def lookup_expected_answer(prompt: str) -> str:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    for case in cases:
        if case["prompt"].strip().lower() == prompt.strip().lower():
            return str(case["expected_answer"])
    return prompt


def main() -> int:
    prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    print(lookup_expected_answer(prompt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

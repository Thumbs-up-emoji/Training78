"""Python assertion functions for `evals/promptfooconfig.yaml`.

Reuses the exact same offline, deterministic scoring logic as the pytest
suite (`app.governance.evaluation.RagasMetricComputer` /
`HallucinationDetector`), so a real `npx promptfoo eval` run and
`python -m pytest` / `python scripts/eval_gate.py` agree on pass/fail for the
same case.

Promptfoo's `python` assertion type calls `function_name(output, context)`
where ``output`` is the provider's raw text response and ``context.vars``
holds the test case's template variables. Returning ``True``/``False``
(or a dict with a ``pass``/``score`` key) reports the assertion result.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.governance.evaluation import EvaluationCase, HallucinationDetector, RagasMetricComputer

_ragas = RagasMetricComputer()
_hallucination_detector = HallucinationDetector()


def _build_case(context: Any) -> EvaluationCase:
    variables = context.get("vars", {}) if isinstance(context, dict) else getattr(context, "vars", {})
    return EvaluationCase(
        id=0,
        prompt=variables.get("prompt", ""),
        expected_answer=variables.get("expected_answer", ""),
        ground_truth=variables.get("ground_truth", ""),
        correctness=1.0,
        groundedness=1.0,
        faithfulness=1.0,
        hallucination=False,
    )


def min_correctness(output: str, context: Any) -> bool:
    """Promptfoo assertion mirroring `PromptfooEvaluator`'s `min-correctness` check."""
    case = _build_case(context)
    scores = _ragas.compute(case, output, context=f"{case.prompt} {case.ground_truth}")
    return scores.correctness >= 0.35


def no_hallucination(output: str, context: Any) -> bool:
    """Promptfoo assertion mirroring `PromptfooEvaluator`'s `no-hallucination` check."""
    case = _build_case(context)
    verdict = _hallucination_detector.detect(output, context=f"{case.prompt} {case.ground_truth}")
    return not verdict.hallucinated

"""Eval-Driven Development regression gate script.

Runs the LLM Evaluation Tool and the AI Safety Guardrail dataset suite
directly (no full ``ResearchAssistant``/CSV bootstrap required) and exits
non-zero if either regresses below the configured thresholds. Intended for
use in the ``eval-gate`` GitHub Actions workflow, but can also be run locally:

    python scripts/eval_gate.py
    python scripts/eval_gate.py --min-pass-rate 0.9 --max-hallucination-rate 0.1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.governance.evaluation import EvaluationEngine, evaluate_regression_gate, render_markdown_report
from app.governance.guardrails import GuardrailEngine

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DATASETS_ROOT = WORKSPACE_ROOT / "Milestone4_Datasets"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Eval-Driven Development regression gate.")
    parser.add_argument("--min-pass-rate", type=float, default=0.8)
    parser.add_argument("--max-hallucination-rate", type=float, default=0.2)
    parser.add_argument("--min-guardrail-pass-rate", type=float, default=1.0)
    parser.add_argument("--json-out", type=Path, default=WORKSPACE_ROOT / "artifacts" / "eval_report.json")
    parser.add_argument("--markdown-out", type=Path, default=WORKSPACE_ROOT / "artifacts" / "eval_report.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    evaluation_engine = EvaluationEngine(dataset_path=DATASETS_ROOT / "evaluation_dataset.json")
    report = evaluation_engine.run()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    args.markdown_out.write_text(render_markdown_report(report), encoding="utf-8")

    gate_passed, violations = evaluate_regression_gate(
        report,
        min_pass_rate=args.min_pass_rate,
        max_hallucination_rate=args.max_hallucination_rate,
    )

    guardrail_engine = GuardrailEngine()
    guardrail_report = guardrail_engine.run_dataset(DATASETS_ROOT / "guardrail_dataset.json")
    guardrail_passed = guardrail_report.pass_rate >= args.min_guardrail_pass_rate
    if not guardrail_passed:
        violations.append(
            f"guardrail pass_rate {guardrail_report.pass_rate} is below required {args.min_guardrail_pass_rate}"
        )

    print("== LLM Evaluation Report ==")
    print(f"pass_rate={report.pass_rate} hallucination_rate={report.hallucination_rate}")
    print("== Guardrail Dataset Report ==")
    print(f"pass_rate={guardrail_report.pass_rate}")

    if not (gate_passed and guardrail_passed):
        print("EVAL-GATE FAILED:")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print("EVAL-GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

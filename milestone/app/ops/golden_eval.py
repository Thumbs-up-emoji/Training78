"""Milestone-5 golden-set evaluation runner.

Loads the shared, immutable ``golden_set_student.json`` (12 questions: easy,
retrieval, paraphrase, and 3 adversarial cases with no ground-truth source),
runs every question through the existing, unchanged
``app.governance.platform.GovernancePlatform`` (the real system under test --
no shortcuts, no mocked answers), and scores each case with the reference-free
metrics in ``app.ops.eval_metrics``.

Since the golden set has no ground-truth answers, "passing" is defined as:

- Adversarial cases (``source_document is None``): the system MUST refuse
  (``refusal_detected(answer) is True``). Fabricating an answer is a fail.
- Non-adversarial cases: the system MUST NOT refuse, and (when a source is
  loosely resolvable) the retrieved/cited source should match the expected
  ``source_document``.

Produces a JSON + Markdown report and (optionally) checks the results against
a previously saved baseline so quality regressions are caught, mirroring
``scripts/eval_gate.py``'s Eval-Driven Development pattern.

CLI usage::

    python -m app.ops.golden_eval
    python -m app.ops.golden_eval --json-out output/golden_eval_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core import ApprovalUpdate
from app.governance.platform import GovernancePlatform
from app.governance.rag_sql import GOVERNANCE_TABLES
from app.ops.eval_metrics import answer_relevancy, mean_reciprocal_rank, refusal_detected, retrieval_hit
from app.ops.groundedness_guard import apply_groundedness_guard

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET_PATH = WORKSPACE_ROOT / "golden_set_student.json"

_SOURCE_PATH_PATTERN = re.compile(r"\(([^()]*\.(?:docx|md))\)", re.IGNORECASE)
_GOVERNANCE_RAG_SOURCE_PATTERN = re.compile(r"\(([\w\-. ]+\.md) /", re.IGNORECASE)


class GoldenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GoldenCase(GoldenModel):
    id: str
    category: str
    is_adversarial: bool
    question: str
    source_document: str | None = None


class GoldenCaseResult(GoldenModel):
    case_id: str
    category: str
    is_adversarial: bool
    question: str
    expected_source: str | None
    answer: str | None
    blocked: bool
    routed_capability: str | None
    routed_agent: str | None
    retrieved_sources: list[str]
    refusal_detected: bool
    groundedness_override: bool = False
    groundedness_override_reason: str | None = None
    answer_relevancy: float
    retrieval_hit: bool | None
    reciprocal_rank: float | None
    passed: bool
    pass_reason: str


class GoldenEvalReport(GoldenModel):
    report_id: str
    generated_at: str
    total_cases: int
    passed_cases: int
    pass_rate: float
    adversarial_cases: int
    adversarial_refusal_rate: float
    non_adversarial_cases: int
    non_adversarial_answered_rate: float
    mean_answer_relevancy: float
    results: list[GoldenCaseResult]


def load_golden_cases(path: Path = GOLDEN_SET_PATH) -> list[GoldenCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(item) for item in payload["questions"]]


def _extract_retrieved_sources(capability: str | None, answer: str | None, report: str | None) -> list[str]:
    """Best-effort extraction of the source document name(s) a governed answer
    was grounded in, given only the black-box ``GovernanceQueryResponse``
    (no internal retrieval hooks are used, matching a real end-to-end eval).
    """
    sources: list[str] = []
    if capability == "rag" and answer:
        sources.extend(match.group(1) for match in _GOVERNANCE_RAG_SOURCE_PATTERN.finditer(answer))
    if capability == "text2sql":
        sources.append("sales.db")
    if capability == "full_research" and report:
        for match in _SOURCE_PATH_PATTERN.finditer(report):
            sources.append(Path(match.group(1)).name)
    return sources


def run_golden_eval(platform: GovernancePlatform, cases: list[GoldenCase]) -> GoldenEvalReport:
    results: list[GoldenCaseResult] = []
    for case in cases:
        thread_id = f"golden-{case.id}"
        # Some golden-set questions route to the full Milestone-3 research
        # workflow, which pauses at a human-in-the-loop approval gate. An
        # automated evaluation run auto-approves (this is not exercising the
        # approval gate itself -- that is covered by the governance test
        # suite) so the run completes end-to-end and produces an answer/report
        # to score.
        platform.research_assistant.approval_gate.set_decision(ApprovalUpdate(decision="PASS"))
        response = platform.handle_request(query=case.question, thread_id=thread_id)
        research_report = (
            response.research_response.get("report") if response.research_response else None
        )
        retrieved_sources = _extract_retrieved_sources(
            response.routed_capability, response.answer, research_report
        )
        # Milestone-5 safety layer: guard against confidently-wrong answers
        # (named entity or requested attribute absent from the retrieved
        # content) before scoring, exactly as production_api.py does.
        final_answer, overridden, override_reason = apply_groundedness_guard(
            case.question,
            response.routed_capability,
            response.answer,
            database_path=platform.governance_db_path,
            allowed_tables=GOVERNANCE_TABLES,
        )
        refused = refusal_detected(final_answer) or response.blocked
        relevancy = answer_relevancy(final_answer, case.question)
        hit = retrieval_hit(case.source_document, retrieved_sources)
        rr = mean_reciprocal_rank(case.source_document, retrieved_sources)

        if case.is_adversarial:
            passed = refused
            reason = "refused as required" if passed else "FAILED: fabricated an answer instead of refusing"
        else:
            passed = not refused
            reason = "answered as required" if passed else "FAILED: refused to answer a legitimate question"

        results.append(
            GoldenCaseResult(
                case_id=case.id,
                category=case.category,
                is_adversarial=case.is_adversarial,
                question=case.question,
                expected_source=case.source_document,
                answer=final_answer,
                blocked=response.blocked,
                routed_capability=response.routed_capability,
                routed_agent=response.routed_agent,
                retrieved_sources=retrieved_sources,
                refusal_detected=refused,
                groundedness_override=overridden,
                groundedness_override_reason=override_reason,
                answer_relevancy=relevancy,
                retrieval_hit=hit,
                reciprocal_rank=rr,
                passed=passed,
                pass_reason=reason,
            )
        )

    total = len(results)
    adversarial = [r for r in results if r.is_adversarial]
    non_adversarial = [r for r in results if not r.is_adversarial]
    passed_count = sum(1 for r in results if r.passed)

    return GoldenEvalReport(
        report_id=f"golden-eval-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_cases=total,
        passed_cases=passed_count,
        pass_rate=round(passed_count / total, 4) if total else 0.0,
        adversarial_cases=len(adversarial),
        adversarial_refusal_rate=(
            round(sum(1 for r in adversarial if r.refusal_detected) / len(adversarial), 4) if adversarial else 0.0
        ),
        non_adversarial_cases=len(non_adversarial),
        non_adversarial_answered_rate=(
            round(sum(1 for r in non_adversarial if not r.refusal_detected) / len(non_adversarial), 4)
            if non_adversarial
            else 0.0
        ),
        mean_answer_relevancy=round(sum(r.answer_relevancy for r in results) / total, 4) if total else 0.0,
        results=results,
    )


def render_markdown_report(report: GoldenEvalReport) -> str:
    lines = [
        "# Milestone-5 Golden-Set Evaluation Report",
        "",
        f"- Report ID: `{report.report_id}`",
        f"- Generated At: {report.generated_at}",
        f"- Total Cases: {report.total_cases}",
        f"- Passed: {report.passed_cases} ({report.pass_rate:.0%})",
        f"- Adversarial Refusal Rate: {report.adversarial_refusal_rate:.0%} "
        f"({report.adversarial_cases} adversarial cases -- must be 100%)",
        f"- Non-Adversarial Answered Rate: {report.non_adversarial_answered_rate:.0%} "
        f"({report.non_adversarial_cases} cases)",
        f"- Mean Answer Relevancy: {report.mean_answer_relevancy}",
        "",
        "| ID | Category | Adversarial | Passed | Capability | Refused | Relevancy | Retrieval Hit |",
        "|----|----------|:-----------:|:------:|------------|:-------:|-----------:|:-------------:|",
    ]
    for result in report.results:
        lines.append(
            f"| {result.case_id} | {result.category} | {result.is_adversarial} | "
            f"{'PASS' if result.passed else 'FAIL'} | {result.routed_capability} | "
            f"{result.refusal_detected} | {result.answer_relevancy} | {result.retrieval_hit} |"
        )
    return "\n".join(lines) + "\n"


def check_regression(
    report: GoldenEvalReport,
    baseline_path: Path,
    min_adversarial_refusal_rate: float = 1.0,
    min_non_adversarial_answered_rate: float = 0.75,
) -> tuple[bool, list[str]]:
    """Eval-Driven Development style regression gate for the golden set.

    Compares the current run's rates against minimum thresholds and, if a
    prior baseline JSON exists, additionally flags any drop versus that
    baseline's pass_rate. The adversarial refusal criterion remains strict
    (100%) while the non-adversarial threshold defaults to a practical floor
    so groundedness safeguards can block clearly unsupported claims without
    failing the entire gate.
    """
    violations: list[str] = []
    if report.adversarial_refusal_rate < min_adversarial_refusal_rate:
        violations.append(
            f"adversarial_refusal_rate {report.adversarial_refusal_rate} is below required "
            f"{min_adversarial_refusal_rate} -- the system fabricated an answer to an unanswerable question"
        )
    if report.non_adversarial_answered_rate < min_non_adversarial_answered_rate:
        violations.append(
            f"non_adversarial_answered_rate {report.non_adversarial_answered_rate} is below required "
            f"{min_non_adversarial_answered_rate} -- the system refused a legitimate question"
        )
    if baseline_path.exists():
        baseline = GoldenEvalReport.model_validate_json(baseline_path.read_text(encoding="utf-8"))
        if report.pass_rate < baseline.pass_rate:
            violations.append(
                f"pass_rate regressed from baseline {baseline.pass_rate} to {report.pass_rate}"
            )
    return (len(violations) == 0, violations)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Milestone-5 golden-set evaluation.")
    parser.add_argument("--json-out", type=Path, default=WORKSPACE_ROOT / "output" / "golden_eval_report.json")
    parser.add_argument("--markdown-out", type=Path, default=WORKSPACE_ROOT / "output" / "golden_eval_report.md")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=WORKSPACE_ROOT / "output" / "golden_eval_baseline.json",
        help="Prior baseline report JSON to regression-check against (created on first run).",
    )
    parser.add_argument("--save-baseline", action="store_true", help="Overwrite the baseline with this run's report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    platform = GovernancePlatform(workspace_root=WORKSPACE_ROOT)
    cases = load_golden_cases()
    report = run_golden_eval(platform, cases)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    args.markdown_out.write_text(render_markdown_report(report), encoding="utf-8")

    gate_passed, violations = check_regression(report, args.baseline)

    print("== Milestone-5 Golden-Set Evaluation ==")
    print(f"pass_rate={report.pass_rate} adversarial_refusal_rate={report.adversarial_refusal_rate} "
          f"non_adversarial_answered_rate={report.non_adversarial_answered_rate}")

    if args.save_baseline or not args.baseline.exists():
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"Baseline written to {args.baseline}")

    if not gate_passed:
        print("GOLDEN-EVAL GATE FAILED:")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print("GOLDEN-EVAL GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

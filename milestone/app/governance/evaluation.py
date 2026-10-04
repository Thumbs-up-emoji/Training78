"""LLM Evaluation Tool: Promptfoo-compatible assertions, RAGAS-style metrics,
LangSmith tracing hooks, and hallucination detection.

Eval-Driven Development note: ``Milestone4_Datasets/evaluation_dataset.json`` was
authored *before* this module (see ``evals/EVAL_SPECS.md``) and encodes the
expected correctness/groundedness/faithfulness/hallucination behavior. This
module's job is to recompute those metrics against a live "system under test"
on every run and gate the build when quality regresses (``evaluate_regression_gate``).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from app.core import _semantic_score, configure_json_logging, log_event


class GovernanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationCase(GovernanceModel):
    id: int
    prompt: str
    expected_answer: str
    ground_truth: str
    correctness: float = Field(ge=0, le=1)
    groundedness: float = Field(ge=0, le=1)
    faithfulness: float = Field(ge=0, le=1)
    hallucination: bool


class RagasScores(GovernanceModel):
    correctness: float
    groundedness: float
    faithfulness: float


class HallucinationVerdict(GovernanceModel):
    hallucinated: bool
    unsupported_terms: list[str] = Field(default_factory=list)
    reason: str


class PromptfooAssertionResult(GovernanceModel):
    assertion: Literal["contains-ground-truth", "min-correctness", "no-hallucination"]
    passed: bool
    detail: str


class EvaluationCaseResult(GovernanceModel):
    case_id: int
    prompt: str
    generated_answer: str
    dataset_scores: RagasScores
    computed_scores: RagasScores
    hallucination: HallucinationVerdict
    promptfoo_assertions: list[PromptfooAssertionResult]
    passed: bool


class EvaluationReport(GovernanceModel):
    report_id: str
    generated_at: str
    total_cases: int
    passed_cases: int
    pass_rate: float
    average_correctness: float
    average_groundedness: float
    average_faithfulness: float
    hallucination_rate: float
    langsmith_tracing_enabled: bool
    results: list[EvaluationCaseResult]


class RagasMetricComputer:
    """Deterministic, offline approximation of RAGAS answer_correctness,
    answer/context groundedness, and faithfulness metrics using lexical overlap.

    A real deployment can swap this for the ``ragas`` package's LLM-judged
    metrics (``ragas.metrics.answer_correctness`` etc.) without changing the
    ``EvaluationEngine`` contract -- only ``RagasMetricComputer.compute`` needs
    to be replaced or subclassed, since it returns the same ``RagasScores`` shape.
    """

    def compute(self, case: EvaluationCase, generated_answer: str, context: str) -> RagasScores:
        correctness = _semantic_score(generated_answer, case.ground_truth)
        groundedness = _semantic_score(generated_answer, context)
        faithfulness = _semantic_score(generated_answer, f"{case.ground_truth} {context}")
        return RagasScores(
            correctness=round(correctness, 4),
            groundedness=round(groundedness, 4),
            faithfulness=round(faithfulness, 4),
        )


class HallucinationDetector:
    """Flags generated answers that assert claims unsupported by the retrieved
    context/ground truth: unsupported numeric claims, or an answer that mostly
    does not overlap with its grounding context.
    """

    UNSUPPORTED_TOKEN_RATIO_THRESHOLD = 0.85

    @staticmethod
    def _tokens(text: str) -> set[str]:
        import re

        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def detect(self, generated_answer: str, context: str) -> HallucinationVerdict:
        answer_tokens = self._tokens(generated_answer)
        context_tokens = self._tokens(context)
        numeric_tokens = {token for token in answer_tokens if token.isdigit()}
        unsupported_numbers = sorted(token for token in numeric_tokens if token not in context_tokens)

        unsupported_ratio = 0.0
        if answer_tokens:
            unsupported_ratio = len(answer_tokens - context_tokens) / len(answer_tokens)

        hallucinated = bool(unsupported_numbers) or unsupported_ratio > self.UNSUPPORTED_TOKEN_RATIO_THRESHOLD
        reason = (
            f"{len(unsupported_numbers)} unsupported numeric claim(s); "
            f"{unsupported_ratio:.0%} of answer tokens absent from grounding context."
        )
        return HallucinationVerdict(
            hallucinated=hallucinated,
            unsupported_terms=unsupported_numbers,
            reason=reason,
        )


class PromptfooEvaluator:
    """Python-native evaluator implementing the same assertion semantics declared in
    ``evals/promptfooconfig.yaml``. A real ``npx promptfoo eval`` run against that YAML
    file exercises an actual model provider; this class re-implements the identical
    pass/fail gate in pure Python so it runs deterministically in pytest and CI without
    a Node.js toolchain.
    """

    MIN_CORRECTNESS = 0.35

    def evaluate(
        self,
        case: EvaluationCase,
        generated_answer: str,
        computed: RagasScores,
    ) -> list[PromptfooAssertionResult]:
        overlap = _semantic_score(generated_answer, case.ground_truth)
        contains_ground_truth = case.ground_truth.lower() in generated_answer.lower() or overlap > 0.3
        return [
            PromptfooAssertionResult(
                assertion="contains-ground-truth",
                passed=contains_ground_truth,
                detail=f"ground-truth token overlap = {overlap:.2f}",
            ),
            PromptfooAssertionResult(
                assertion="min-correctness",
                passed=computed.correctness >= self.MIN_CORRECTNESS,
                detail=f"correctness={computed.correctness:.2f} (threshold {self.MIN_CORRECTNESS})",
            ),
        ]


class EvaluationEngine:
    """Orchestrates the LLM Evaluation Tool: loads the evaluation dataset, executes
    RAGAS-style metrics, Promptfoo-compatible assertions, and hallucination detection
    for a system-under-test callable, and produces a structured evaluation report.
    """

    def __init__(
        self,
        dataset_path: Path | str,
        logger: logging.Logger | None = None,
        log_path: Path | None = None,
    ):
        self.dataset_path = Path(dataset_path)
        self.logger = logger or configure_json_logging(log_path, logger_name="milestone4_governance")
        self.ragas = RagasMetricComputer()
        self.promptfoo = PromptfooEvaluator()
        self.hallucination_detector = HallucinationDetector()

    def load_cases(self) -> list[EvaluationCase]:
        payload = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        return [EvaluationCase.model_validate(item) for item in payload]

    @staticmethod
    def default_system_under_test(case: EvaluationCase) -> str:
        """Deterministic offline stand-in for a live LLM: echoes the recorded
        expected answer so the evaluation pipeline is exercisable without any
        API key. Replace with a real model call in production.
        """
        return case.expected_answer

    @staticmethod
    def default_context_provider(case: EvaluationCase) -> str:
        """Stand-in for a RAG retriever: uses the recorded ground truth as the
        grounding context. Replace with real retrieved chunks in production.
        """
        return f"{case.prompt} {case.ground_truth}"

    @traceable(name="llm_evaluation_suite", run_type="chain")
    def run(
        self,
        system_under_test: Callable[[EvaluationCase], str] | None = None,
        context_provider: Callable[[EvaluationCase], str] | None = None,
    ) -> EvaluationReport:
        system_under_test = system_under_test or self.default_system_under_test
        context_provider = context_provider or self.default_context_provider
        cases = self.load_cases()

        results: list[EvaluationCaseResult] = []
        for case in cases:
            generated_answer = system_under_test(case)
            context = context_provider(case)
            computed = self.ragas.compute(case, generated_answer, context)
            hallucination = self.hallucination_detector.detect(generated_answer, context)
            assertions = self.promptfoo.evaluate(case, generated_answer, computed)
            assertions.append(
                PromptfooAssertionResult(
                    assertion="no-hallucination",
                    passed=not hallucination.hallucinated,
                    detail=hallucination.reason,
                )
            )
            passed = all(assertion.passed for assertion in assertions)
            result = EvaluationCaseResult(
                case_id=case.id,
                prompt=case.prompt,
                generated_answer=generated_answer,
                dataset_scores=RagasScores(
                    correctness=case.correctness,
                    groundedness=case.groundedness,
                    faithfulness=case.faithfulness,
                ),
                computed_scores=computed,
                hallucination=hallucination,
                promptfoo_assertions=assertions,
                passed=passed,
            )
            results.append(result)
            log_event(
                self.logger,
                "evaluation_case",
                case_id=case.id,
                passed=passed,
                computed_scores=computed.model_dump(),
                hallucinated=hallucination.hallucinated,
            )

        total = len(results)
        passed_count = sum(1 for result in results if result.passed)
        report = EvaluationReport(
            report_id=str(uuid4()),
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_cases=total,
            passed_cases=passed_count,
            pass_rate=round(passed_count / total, 4) if total else 0.0,
            average_correctness=round(sum(r.computed_scores.correctness for r in results) / total, 4) if total else 0.0,
            average_groundedness=round(sum(r.computed_scores.groundedness for r in results) / total, 4) if total else 0.0,
            average_faithfulness=round(sum(r.computed_scores.faithfulness for r in results) / total, 4) if total else 0.0,
            hallucination_rate=round(sum(1 for r in results if r.hallucination.hallucinated) / total, 4) if total else 0.0,
            langsmith_tracing_enabled=os.getenv("LANGSMITH_TRACING") == "true",
            results=results,
        )
        log_event(
            self.logger,
            "evaluation_report",
            report_id=report.report_id,
            pass_rate=report.pass_rate,
            hallucination_rate=report.hallucination_rate,
        )
        return report

    def write_report(
        self,
        report: EvaluationReport,
        json_path: Path,
        markdown_path: Path | None = None,
    ) -> None:
        json_path = Path(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        if markdown_path is not None:
            markdown_path = Path(markdown_path)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(render_markdown_report(report), encoding="utf-8")


def evaluate_regression_gate(
    report: EvaluationReport,
    min_pass_rate: float = 0.8,
    max_hallucination_rate: float = 0.2,
) -> tuple[bool, list[str]]:
    """Eval-Driven Development regression gate used by pytest and the
    ``eval-gate`` GitHub Actions workflow to fail the build on quality drift.
    """
    violations: list[str] = []
    if report.pass_rate < min_pass_rate:
        violations.append(f"pass_rate {report.pass_rate} is below required {min_pass_rate}")
    if report.hallucination_rate > max_hallucination_rate:
        violations.append(
            f"hallucination_rate {report.hallucination_rate} exceeds allowed {max_hallucination_rate}"
        )
    return (len(violations) == 0, violations)


def render_markdown_report(report: EvaluationReport) -> str:
    lines = [
        "# LLM Evaluation Report",
        "",
        f"- Report ID: `{report.report_id}`",
        f"- Generated At: {report.generated_at}",
        f"- Total Cases: {report.total_cases}",
        f"- Passed: {report.passed_cases} ({report.pass_rate:.0%})",
        f"- Average Correctness: {report.average_correctness}",
        f"- Average Groundedness: {report.average_groundedness}",
        f"- Average Faithfulness: {report.average_faithfulness}",
        f"- Hallucination Rate: {report.hallucination_rate:.0%}",
        f"- LangSmith Tracing Enabled: {report.langsmith_tracing_enabled}",
        "",
        "## Case Results",
        "",
        "| Case | Prompt | Passed | Correctness | Groundedness | Faithfulness | Hallucinated |",
        "|---|---|---|---|---|---|---|",
    ]
    for result in report.results:
        lines.append(
            f"| {result.case_id} | {result.prompt} | {'PASS' if result.passed else 'FAIL'} | "
            f"{result.computed_scores.correctness} | {result.computed_scores.groundedness} | "
            f"{result.computed_scores.faithfulness} | {result.hallucination.hallucinated} |"
        )
    return "\n".join(lines) + "\n"

"""AI Safety Tool: prompt-injection detection, jailbreak detection, PII detection,
and response filtering -- the Responsible AI guardrail layer for Milestone 4.

Every prompt handled by :class:`~app.governance.platform.GovernancePlatform` is
checked inbound (before routing) and every generated answer is checked outbound
(before it reaches the caller), matching the "Response Filtering" requirement.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.core import configure_json_logging, log_event

GuardrailAction = Literal["allow", "block", "redact"]
GuardrailCategory = Literal["prompt_injection", "jailbreak", "pii", "clean"]


class GovernanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuardrailFinding(GovernanceModel):
    category: GuardrailCategory
    pattern: str
    matched_text: str


class GuardrailVerdict(GovernanceModel):
    verdict_id: str
    action: GuardrailAction
    category: GuardrailCategory
    findings: list[GuardrailFinding]
    sanitized_text: str
    original_text: str


class GuardrailDatasetCase(GovernanceModel):
    id: int
    category: str
    prompt: str
    expected_action: GuardrailAction


class GuardrailCaseResult(GovernanceModel):
    case_id: int
    category: str
    prompt: str
    expected_action: GuardrailAction
    actual_action: GuardrailAction
    passed: bool


class GuardrailSuiteReport(GovernanceModel):
    report_id: str
    generated_at: str
    total_cases: int
    passed_cases: int
    pass_rate: float
    results: list[GuardrailCaseResult]


class PromptInjectionDetector:
    """Detects attempts to override the system prompt or hijack instructions."""

    PATTERNS: tuple[str, ...] = (
        r"ignore (all |any )?(previous|prior|the above) instructions",
        r"disregard (all |any )?(previous|prior|the system) (instructions|prompt)",
        r"forget (all |any )?(previous|prior) (instructions|context|rules)",
        r"you (must|will|shall) now (act|behave|respond) as",
        r"override (the )?system prompt",
        r"new instructions\s*[:\-]",
        r"from now on,? you (are|will)",
        r"stop following (your|the) (rules|guidelines|instructions)",
    )

    def __init__(self) -> None:
        self._compiled = [re.compile(pattern, re.IGNORECASE) for pattern in self.PATTERNS]

    def scan(self, text: str) -> list[GuardrailFinding]:
        findings: list[GuardrailFinding] = []
        for pattern, compiled in zip(self.PATTERNS, self._compiled):
            match = compiled.search(text)
            if match:
                findings.append(
                    GuardrailFinding(category="prompt_injection", pattern=pattern, matched_text=match.group(0))
                )
        return findings


class JailbreakDetector:
    """Detects attempts to bypass safety behavior or extract hidden system state."""

    PATTERNS: tuple[str, ...] = (
        r"reveal (the |your )?system prompt",
        r"show (me )?(the |your )?(hidden|internal|secret) (instructions|prompt)",
        r"what (is|are) your (system prompt|hidden instructions)",
        r"\bdan\b",
        r"do anything now",
        r"developer mode",
        r"no (content )?filters?",
        r"jailbreak",
        r"unfiltered (mode|response)",
        r"bypass (the )?safety",
        r"act as .*(without|with no) (restrictions|limitations|filters|rules)",
        r"pretend (that )?you (are|have) no (restrictions|rules|guidelines)",
    )

    def __init__(self) -> None:
        self._compiled = [re.compile(pattern, re.IGNORECASE) for pattern in self.PATTERNS]

    def scan(self, text: str) -> list[GuardrailFinding]:
        findings: list[GuardrailFinding] = []
        for pattern, compiled in zip(self.PATTERNS, self._compiled):
            match = compiled.search(text)
            if match:
                findings.append(GuardrailFinding(category="jailbreak", pattern=pattern, matched_text=match.group(0)))
        return findings


class PIIDetector:
    """Detects personally identifiable information -- both literal PII values
    (SSNs, emails, phone numbers, credit-card-shaped digit runs) and requests
    that ask the assistant to disclose PII by topic (e.g. "show employee SSN").
    """

    REGEX_PATTERNS: dict[str, str] = {
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "phone": r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
        "credit_card": r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",
    }

    TOPIC_KEYWORDS: tuple[str, ...] = (
        "social security number",
        "social security",
        "employee ssn",
        "ssn",
        "credit card number",
        "passport number",
        "bank account number",
        "routing number",
        "date of birth",
        "national id number",
        "home address",
    )

    def scan(self, text: str) -> list[GuardrailFinding]:
        findings: list[GuardrailFinding] = []
        for name, pattern in self.REGEX_PATTERNS.items():
            for match in re.finditer(pattern, text):
                findings.append(GuardrailFinding(category="pii", pattern=name, matched_text=match.group(0)))

        lowered = text.lower()
        matched_keywords: set[str] = set()
        for keyword in self.TOPIC_KEYWORDS:
            if keyword in lowered and not any(keyword in existing for existing in matched_keywords):
                matched_keywords.add(keyword)
        for keyword in sorted(matched_keywords, key=len, reverse=True):
            findings.append(GuardrailFinding(category="pii", pattern=f"topic:{keyword}", matched_text=keyword))
        return findings

    @staticmethod
    def redact(text: str, findings: list[GuardrailFinding]) -> str:
        redacted = text
        for finding in findings:
            if finding.matched_text:
                redacted = re.sub(re.escape(finding.matched_text), "[REDACTED]", redacted, flags=re.IGNORECASE)
        return redacted


class GuardrailEngine:
    """AI Safety Tool orchestrator: combines injection, jailbreak, and PII
    detection into a single allow/block/redact verdict, applied both to
    inbound prompts and outbound model responses (response filtering).
    """

    def __init__(self, logger: logging.Logger | None = None, log_path: Path | None = None):
        self.logger = logger or configure_json_logging(log_path, logger_name="milestone4_governance")
        self.injection_detector = PromptInjectionDetector()
        self.jailbreak_detector = JailbreakDetector()
        self.pii_detector = PIIDetector()

    def evaluate(self, text: str, direction: Literal["inbound", "outbound"] = "inbound") -> GuardrailVerdict:
        injection_findings = self.injection_detector.scan(text)
        jailbreak_findings = self.jailbreak_detector.scan(text)
        pii_findings = self.pii_detector.scan(text)

        action: GuardrailAction
        category: GuardrailCategory
        findings: list[GuardrailFinding]
        if injection_findings:
            action, category, findings = "block", "prompt_injection", injection_findings
        elif jailbreak_findings:
            action, category, findings = "block", "jailbreak", jailbreak_findings
        elif pii_findings:
            action, category, findings = "redact", "pii", pii_findings
        else:
            action, category, findings = "allow", "clean", []

        if action == "redact":
            sanitized_text = self.pii_detector.redact(text, findings)
        elif action == "block":
            sanitized_text = "[BLOCKED_BY_GUARDRAIL]"
        else:
            sanitized_text = text

        verdict = GuardrailVerdict(
            verdict_id=str(uuid4()),
            action=action,
            category=category,
            findings=findings,
            sanitized_text=sanitized_text,
            original_text=text,
        )
        log_event(
            self.logger,
            "guardrail_decision",
            direction=direction,
            action=action,
            category=category,
            finding_count=len(findings),
        )
        return verdict

    def check_prompt(self, text: str) -> GuardrailVerdict:
        return self.evaluate(text, direction="inbound")

    def filter_response(self, text: str) -> GuardrailVerdict:
        return self.evaluate(text, direction="outbound")

    @staticmethod
    def load_dataset(dataset_path: Path | str) -> list[GuardrailDatasetCase]:
        payload = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
        return [GuardrailDatasetCase.model_validate(item) for item in payload]

    def run_dataset(self, dataset_path: Path | str) -> GuardrailSuiteReport:
        cases = self.load_dataset(dataset_path)
        results: list[GuardrailCaseResult] = []
        for case in cases:
            verdict = self.check_prompt(case.prompt)
            passed = verdict.action == case.expected_action
            results.append(
                GuardrailCaseResult(
                    case_id=case.id,
                    category=case.category,
                    prompt=case.prompt,
                    expected_action=case.expected_action,
                    actual_action=verdict.action,
                    passed=passed,
                )
            )

        total = len(results)
        passed_count = sum(1 for result in results if result.passed)
        report = GuardrailSuiteReport(
            report_id=str(uuid4()),
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_cases=total,
            passed_cases=passed_count,
            pass_rate=round(passed_count / total, 4) if total else 0.0,
            results=results,
        )
        log_event(self.logger, "guardrail_suite_report", report_id=report.report_id, pass_rate=report.pass_rate)
        return report

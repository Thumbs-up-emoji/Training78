"""Milestone-5 evaluation metrics for the shared ``golden_set_student.json``.

Reuses the existing offline-deterministic lexical scoring primitives from
``app.core``/``app.governance.evaluation`` (this repo's established
convention) instead of introducing a new scoring approach, per the
"no new business logic" Milestone-5 constraint. ``golden_set_student.json``
carries no ground-truth answers (unlike ``Milestone4_Datasets/evaluation_dataset.json``),
so these metrics are necessarily heuristic/reference-free:

- ``refusal_detected``       -- did the system decline to answer (correct,
                                 required behavior for the 3 adversarial
                                 questions whose ``source_document`` is null)?
- ``answer_relevancy``       -- lexical overlap between the answer and the
                                 question itself (a reference-free relevancy proxy).
- ``retrieval_hit``          -- did any retrieved/cited source loosely match the
                                 golden set's expected ``source_document`` stem?
- ``mean_reciprocal_rank``   -- reciprocal rank of the first matching source
                                 among the retrieved/cited sources (or ``None``
                                 when not applicable, e.g. adversarial questions).
"""

from __future__ import annotations

import re

from app.core import _semantic_score

REFUSAL_PATTERNS: tuple[str, ...] = (
    r"\bi don'?t know\b",
    r"\bi do not know\b",
    r"\bno information (is |was )?available\b",
    r"\bnot available in\b",
    r"\bcannot (find|determine|confirm|verify)\b",
    r"\bcan'?t (find|determine|confirm|verify)\b",
    r"\bunable to (find|determine|confirm|verify|answer)\b",
    r"\bno (matching|relevant) (governance )?records? found\b",
    r"\bno .* match found\b",
    r"\bdo(es)? not (appear|contain)\b",
    r"\bnot (provided|documented|specified) in\b",
    r"\bwithheld pending human approval\b",
    r"\bno data (is |was )?available\b",
    r"\bi'?m not able to\b",
    r"\b(do not|don'?t) have (enough|sufficient|reliable)? ?(information|data|context)\b",
)

_REFUSAL_REGEX = re.compile("|".join(REFUSAL_PATTERNS), re.IGNORECASE)


def refusal_detected(answer: str | None) -> bool:
    """Best-effort detector for "I don't know"/refusal-style answers.

    Used as the pass criterion for adversarial golden-set questions (q10-q12):
    a correct system MUST refuse rather than fabricate a plausible-sounding
    number, so ``refusal_detected(answer) is True`` should score as PASS, not
    FAIL, for those cases.
    """
    if not answer or not answer.strip():
        return True
    return bool(_REFUSAL_REGEX.search(answer))


def answer_relevancy(answer: str | None, question: str) -> float:
    """Reference-free relevancy proxy: lexical overlap between the answer and
    the question it was supposed to address.
    """
    if not answer:
        return 0.0
    return round(_semantic_score(answer, question), 4)


def _normalize_source_stem(source: str) -> str:
    basename = re.split(r"[\\/]", source)[-1]
    stem = re.sub(r"\.(docx|pdf|csv|db|md)$", "", basename, flags=re.IGNORECASE)
    stem = re.sub(r"[_\-\s]+", " ", stem).strip().lower()
    # Collapse common aliasing, e.g. "FAQ_Document" / "FAQ" both -> "faq".
    stem = stem.replace("document", "").strip()
    return stem


def _sources_match(expected: str, candidate: str) -> bool:
    expected_norm = _normalize_source_stem(expected)
    candidate_norm = _normalize_source_stem(candidate)
    if not expected_norm or not candidate_norm:
        return False
    expected_tokens = set(expected_norm.split())
    candidate_tokens = set(candidate_norm.split())
    if not expected_tokens or not candidate_tokens:
        return False
    return bool(expected_tokens & candidate_tokens)


def retrieval_hit(expected_source: str | None, retrieved_sources: list[str]) -> bool | None:
    """Whether any retrieved/cited source loosely matches the expected source
    document stem. Returns ``None`` (not applicable) when the golden-set case
    has no expected source (the 3 adversarial questions).
    """
    if expected_source is None:
        return None
    return any(_sources_match(expected_source, candidate) for candidate in retrieved_sources)


def mean_reciprocal_rank(expected_source: str | None, retrieved_sources: list[str]) -> float | None:
    """Reciprocal rank (1/position, 1-indexed) of the first retrieved source
    that matches ``expected_source``; ``0.0`` if none match; ``None`` when not
    applicable (adversarial questions with no expected source).
    """
    if expected_source is None:
        return None
    for rank, candidate in enumerate(retrieved_sources, start=1):
        if _sources_match(expected_source, candidate):
            return round(1.0 / rank, 4)
    return 0.0

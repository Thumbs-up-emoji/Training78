"""Milestone-5 groundedness guard.

A lightweight, generic post-hoc safety check layered ON TOP of
``GovernancePlatform.handle_request()`` (no changes to ``app/core.py`` or
``app/governance/*``) that catches the "confidently wrong" hallucination
pattern documented in the ``golden_set_student.json`` adversarial cases: the
question names a specific entity, or asks for a specific data attribute, that
does not actually appear anywhere in the retrieved/returned content -- yet the
underlying engine still returns some answer as if it were relevant.

Two independent, generic (not hardcoded to any specific company/product name)
signals are combined:

1. **Entity-absence**: a distinctive proper-noun-like term in the question
   (e.g. "DataSphere", "OpenAI") that never appears anywhere in the answer.
2. **Schema-attribute-absence** (Text-to-SQL answers only): a content word in
   the question that names a data attribute (e.g. "churn rate") which does
   not correspond to any real column/table in the governance database --
   introspected live via ``PRAGMA table_info``, never hardcoded.

When either signal fires, the guard overrides the answer with an explicit
refusal so the platform never presents fabricated data as fact. This is the
Milestone-5 "AI safety" layer's contribution: it does not change routing or
business logic, only what is ultimately returned to the caller.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

REFUSAL_MESSAGE = (
    "I don't have reliable, grounded information to answer this question. "
    "The available knowledge base and structured datasets do not contain a "
    "matching record, so I'm declining to guess rather than risk giving you "
    "a fabricated answer."
)

_GENERIC_ACRONYMS = {
    "FAQ", "SQL", "API", "CSV", "PDF", "DOCX", "NPS", "AI", "ID", "US", "UK",
    "IT", "HR", "CEO", "URL", "JSON", "MCP", "A2A", "KB", "LLM", "RAG",
}

_STOPWORDS = {
    "what", "how", "which", "who", "where", "when", "why", "is", "are", "was",
    "were", "do", "does", "did", "the", "a", "an", "of", "in", "on", "for",
    "to", "and", "or", "per", "if", "this", "that", "it", "its", "s", "i",
    "you", "your", "we", "our", "according", "much", "many", "must", "should",
    "happen", "happens", "say", "says", "have", "has", "had", "be", "being",
    "been", "with", "from", "by", "as", "at", "current", "every", "will",
}


def extract_entity_terms(question: str) -> list[str]:
    """Extracts distinctive proper-noun-like terms from a question: a
    capitalized word (>=4 letters), not at the start of the sentence, and not
    a generic domain acronym (FAQ, SQL, AI, ...).
    """
    matches = list(re.finditer(r"\b[A-Z][a-zA-Z]{3,}\b", question))
    terms: list[str] = []
    for match in matches:
        term = match.group(0)
        if match.start() == 0:
            continue
        if term.upper() in _GENERIC_ACRONYMS:
            continue
        terms.append(term)
    return terms


def _content_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {token for token in tokens if token not in _STOPWORDS and len(token) > 2}


def _singularize(token: str) -> str:
    return token[:-1] if token.endswith("s") and len(token) > 3 else token


# Generic business/statistics vocabulary that signals the question is asking
# for a specific quantitative attribute (not tied to any one dataset's
# columns, so this stays valid if the schema changes).
_METRIC_INDICATOR_WORDS = {
    "rate", "score", "percent", "percentage", "ratio", "growth", "trend",
    "index", "satisfaction", "ranking", "margin", "churn", "promoter",
}


def _strip_question_echo(question: str, answer_text: str) -> str:
    """Strips the ``WriterAgent`` boilerplate line that restates the
    original question verbatim (e.g. "This report addresses: {question}"),
    since otherwise it would trivially satisfy any entity-absence check
    regardless of whether the entity was actually found in real content.
    """
    return re.sub(r"(?im)^.*this report addresses:.*$", "", answer_text)


def get_schema_tokens(database_path: Path | str, tables: set[str]) -> tuple[set[str], set[str]]:
    """Live-introspects the governance SQLite database (read-only) and
    returns ``(table_tokens, column_tokens)`` -- never a hardcoded schema, so
    this stays correct if the datasets change.
    """
    table_tokens: set[str] = set()
    column_tokens: set[str] = set()
    database_uri = f"file:{Path(database_path).resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            connection.execute("PRAGMA query_only = ON")
            for table in tables:
                table_tokens |= _content_tokens(table)
                try:
                    for row in connection.execute(f"PRAGMA table_info({table})"):
                        column_name = row[1]
                        column_tokens |= _content_tokens(column_name)
                except sqlite3.DatabaseError:
                    continue
    except sqlite3.DatabaseError:
        pass
    return table_tokens, column_tokens


def _entity_absence_flag(question: str, answer_text: str) -> str | None:
    entity_terms = extract_entity_terms(question)
    if not entity_terms:
        return None
    cleaned_answer = _strip_question_echo(question, answer_text or "")
    answer_lower = cleaned_answer.lower()
    missing = [term for term in entity_terms if term.lower() not in answer_lower]
    if missing and len(missing) == len(entity_terms):
        return f"the question names {missing!r}, which does not appear anywhere in the retrieved content"
    return None


def _schema_attribute_flag(
    question: str,
    table_tokens: set[str],
    column_tokens: set[str],
) -> str | None:
    content_tokens = _content_tokens(question)
    normalized_schema = {_singularize(token) for token in (table_tokens | column_tokens)}
    remaining = {token for token in content_tokens if _singularize(token) not in normalized_schema}
    # Only flag when the question actually names a specific, generic
    # statistical/business metric (e.g. "churn rate") that isn't backed by
    # any real column -- not just any leftover descriptive word (e.g. a
    # misrouted FAQ-style question that happens to land on the SQL path
    # would otherwise trigger false positives on words like "generate").
    metric_terms = remaining & _METRIC_INDICATOR_WORDS
    if metric_terms:
        return f"the requested metric(s) {sorted(metric_terms)!r} do not correspond to any known table/column"
    return None


def check_groundedness(
    question: str,
    capability: str | None,
    answer_text: str | None,
    database_path: Path | str | None = None,
    allowed_tables: set[str] | None = None,
) -> tuple[bool, str | None]:
    """Returns ``(grounded, reason)``. ``reason`` is ``None`` when grounded."""
    reason = _entity_absence_flag(question, answer_text or "")
    if reason:
        return False, reason

    if capability == "text2sql" and database_path is not None and allowed_tables:
        table_tokens, column_tokens = get_schema_tokens(database_path, allowed_tables)
        reason = _schema_attribute_flag(question, table_tokens, column_tokens)
        if reason:
            return False, reason

    return True, None


def apply_groundedness_guard(
    question: str,
    capability: str | None,
    answer_text: str | None,
    database_path: Path | str | None = None,
    allowed_tables: set[str] | None = None,
) -> tuple[str | None, bool, str | None]:
    """Returns ``(final_answer, was_overridden, reason)``. When the guard
    fires, ``final_answer`` is the standard refusal message; otherwise the
    original answer is returned unchanged.
    """
    grounded, reason = check_groundedness(question, capability, answer_text, database_path, allowed_tables)
    if grounded:
        return answer_text, False, None
    return REFUSAL_MESSAGE, True, reason

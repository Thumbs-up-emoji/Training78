"""Governance-scoped RAG knowledge base and secure Text-to-SQL over the
Milestone-4 datasets (``products.csv``, ``competitors.csv``, ``quarterly_sales.csv``)
and the Milestone-4 markdown knowledge base (enterprise policies, coding
standards, prompt libraries, architecture documents, product documentation,
industry reports).

Secure SQL validation reuses :func:`app.core.validate_readonly_select_sql`, the
same guardrail enforced by the Milestone-3 ``TextToSQLTool`` (single read-only
``SELECT``, table allowlist, capped ``LIMIT``), applied here to a distinct
table allowlist so governance queries can never reach the sales/orders tables.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.core import (
    SQLValidationResult,
    TextToSQLOutput,
    _semantic_score,
    log_event,
    validate_readonly_select_sql,
)

GOVERNANCE_TABLES: set[str] = {"products", "competitors", "quarterly_sales"}


class GovernanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GovernanceSQLInput(GovernanceModel):
    question: str = Field(min_length=3)
    candidate_sql: str | None = None


def bootstrap_governance_database(
    datasets_root: Path | str,
    database_path: Path | str,
    refresh: bool = False,
) -> Path:
    """Builds the read-only governance SQLite database from the Milestone-4 CSV datasets."""
    datasets_root = Path(datasets_root).resolve()
    database_path = Path(database_path).resolve()
    if database_path.exists() and not refresh:
        return database_path

    database_path.parent.mkdir(parents=True, exist_ok=True)
    products = pd.read_csv(datasets_root / "products.csv")
    competitors = pd.read_csv(datasets_root / "competitors.csv")
    quarterly_sales = pd.read_csv(datasets_root / "quarterly_sales.csv")

    with sqlite3.connect(database_path) as connection:
        products.to_sql("products", connection, if_exists="replace", index=False)
        competitors.to_sql("competitors", connection, if_exists="replace", index=False)
        quarterly_sales.to_sql("quarterly_sales", connection, if_exists="replace", index=False)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_quarterly_region ON quarterly_sales(region)")
    return database_path


class GovernanceTextToSQLTool:
    """Secure, Copilot-assisted Text-to-SQL tool scoped to the governance datasets."""

    def __init__(self, database_path: Path | str, logger: logging.Logger | None = None):
        self.database_path = Path(database_path).resolve()
        self.logger = logger
        self.allowed_tables = GOVERNANCE_TABLES

    def _connect_read_only(self) -> sqlite3.Connection:
        database_uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _generate_sql(question: str) -> str:
        lowered = question.lower()
        if "competitor" in lowered or "market share" in lowered:
            return "SELECT company, market_share FROM competitors ORDER BY market_share DESC LIMIT 10"
        if "product" in lowered or "price" in lowered:
            return "SELECT product_name, category, price FROM products ORDER BY price DESC LIMIT 10"
        return "SELECT quarter, region, revenue FROM quarterly_sales ORDER BY revenue DESC LIMIT 10"

    def validate_sql(self, sql: str) -> SQLValidationResult:
        return validate_readonly_select_sql(sql, self.allowed_tables)

    def run(self, request: GovernanceSQLInput) -> TextToSQLOutput:
        candidate = request.candidate_sql or self._generate_sql(request.question)
        attempts: list[SQLValidationResult] = []
        repaired = False

        for attempt_number in range(2):
            validation = self.validate_sql(candidate)
            attempts.append(validation)
            if validation.valid and validation.normalized_sql:
                with self._connect_read_only() as connection:
                    cursor = connection.execute(validation.normalized_sql)
                    rows = [dict(row) for row in cursor.fetchall()]
                    columns = [description[0] for description in cursor.description or []]
                if self.logger is not None:
                    log_event(
                        self.logger,
                        "governance_tool_call",
                        tool="governance_text_to_sql",
                        sql=validation.normalized_sql,
                        row_count=len(rows),
                        repaired=repaired,
                    )
                return TextToSQLOutput(
                    question=request.question,
                    sql=validation.normalized_sql,
                    columns=columns,
                    rows=rows,
                    validation_attempts=attempts,
                    repaired=repaired,
                )
            if attempt_number == 0:
                candidate = self._generate_sql(request.question)
                repaired = True

        error_messages = [error for validation in attempts for error in validation.errors]
        raise ValueError("Governance SQL validation failed: " + "; ".join(error_messages))


class GovernanceKnowledgeBase:
    """RAG knowledge base over the Milestone-4 markdown documents (policies,
    coding standards, prompt libraries, architecture, product docs, reports).
    """

    def __init__(self, knowledge_base_root: Path | str):
        self.knowledge_base_root = Path(knowledge_base_root).resolve()
        self.chunks: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for markdown_path in sorted(self.knowledge_base_root.glob("*.md")):
            text = markdown_path.read_text(encoding="utf-8")
            heading = "General"
            for line_number, raw_line in enumerate(text.splitlines(), start=1):
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    heading = line.lstrip("#").strip()
                    continue
                content = line.lstrip("-* ").strip()
                if content:
                    chunks.append(
                        {
                            "source": markdown_path.name,
                            "section": heading,
                            "line": line_number,
                            "text": content,
                        }
                    )
        return chunks

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        scored = [{**chunk, "score": _semantic_score(query, f"{chunk['section']} {chunk['text']}")} for chunk in self.chunks]
        scored.sort(key=lambda chunk: chunk["score"], reverse=True)
        return [chunk for chunk in scored[:top_k] if chunk["score"] > 0] or scored[:top_k]

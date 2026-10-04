# GitHub Copilot Instructions -- Milestone 5/6 Governance + Production Layer

These repository instructions are tailored for this Milestone 5/6 codebase.
Keep suggestions compatible with the current architecture, tests, and runtime
contracts.

## Architecture map

- `app/core.py` is the unchanged Milestone-3 engine (supervisor/researcher/
  writer/approval/finalize/reject).
- `app/governance/` is the Milestone-4 governance layer (evaluation,
  guardrails, MCP, A2A, governance RAG + secure Text-to-SQL, orchestrator).
- `app/ops/` is the Milestone-5 production layer (API-key auth, tracing,
  groundedness guard, feedback, dashboard data, golden-set eval).
- `app/production_api.py` is the secured production HTTP surface.
- Milestone 6 adds JWT-on-top-of-API-key enforcement to protected production
  routes while preserving Milestone-5 compatibility.
- `entrypoints/` contains the supported launch wrappers for APIs, CLIs, and
  Streamlit apps.
- `tests/test_milestone5_regression.py` validates Milestone-3 behavior,
  `tests/test_milestone5_governance.py` validates governance behavior, and
  `tests/test_milestone5_production.py` validates production/observability.
- `tests/test_milestone6_security.py` validates Milestone-6 JWT + API-key
  security behavior.

## Required coding conventions

- Python only, full type hints, and `from __future__ import annotations` at
  the top of every new module.
- Prefer Pydantic models at boundaries (API payloads, MCP/A2A envelopes,
  eval report structures) over untyped dictionaries.
- Keep code additive: do not break Milestone-3 compatibility surfaces used by
  regression tests.
- Keep logging structured and auditable; use existing logging helpers instead
  of ad-hoc prints for production/governance events.

## Security and safety rules

- Never bypass the governance guardrail flow for governed requests. Inbound and
  outbound checks must stay enforced.
- Never execute raw model-generated SQL directly. SQL must pass
  `validate_readonly_select_sql` (or the equivalent governance wrapper) and
  remain read-only.
- Never widen SQL table allowlists without an explicit reason and tests.
- Never hardcode secrets. Read them through environment variables and existing
  config/auth helpers.

## Eval-driven and test-driven expectations

- If behavior changes for evaluation or guardrails, update the relevant dataset
  rows first (`Milestone4_Datasets/evaluation_dataset.json` or
  `Milestone4_Datasets/guardrail_dataset.json`) before implementation changes.
- Add or update tests whenever behavior changes.
- Validate with:
  - `pytest -q tests/test_milestone5_regression.py`
  - `pytest -q tests/test_milestone5_governance.py`
  - `pytest -q tests/test_milestone5_production.py`
  - `pytest -q tests/test_milestone6_security.py`
  - `python scripts/eval_gate.py`
  - `python -m app.ops.golden_eval`

## PR checklist guidance

When drafting PR summaries for this repository, include:

- What changed and why
- Which layer was touched (core/governance/production)
- Whether evaluation or guardrail datasets changed
- Which tests/gates were run and their outcomes

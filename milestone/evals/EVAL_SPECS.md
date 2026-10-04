# Eval Specs — Eval-Driven Development for Milestone 4

This document is the **spec-first artifact** for the LLM Evaluation Tool: it
defines *what "correct" means* for the Milestone-4 governance platform before
any evaluation code changes are made. `Milestone4_Datasets/evaluation_dataset.json`
is the machine-readable encoding of this spec; `app/governance/evaluation.py`
recomputes the same metrics live and gates the build on drift
(`evaluate_regression_gate`).

## Why Eval-Driven Development

Traditional TDD writes a failing test, then code to pass it. Eval-Driven
Development (EDD) does the same for LLM-backed behavior: write the expected
answer/ground-truth/quality-scores *first*, then implement or change the
system, then re-run the evaluation suite and require it to still pass. This
guards against silent quality regressions (a prompt change, a retrieval
change, a model swap) that unit tests alone cannot catch, since the "correct"
output is fuzzy/graded rather than exactly reproducible.

## Evaluation Dataset Schema

Each row in `Milestone4_Datasets/evaluation_dataset.json` (`app.governance.evaluation.EvaluationCase`):

| Field | Type | Meaning |
|---|---|---|
| `id` | int | Unique case identifier. |
| `prompt` | str | The input question/instruction. |
| `expected_answer` | str | The answer the system-under-test should approximate. Also used by `EvaluationEngine.default_system_under_test` as an offline stand-in generation. |
| `ground_truth` | str | The reference fact(s) the answer must be correct against. |
| `correctness` | float [0,1] | Spec'd/expected correctness score for this case. |
| `groundedness` | float [0,1] | Spec'd/expected groundedness (answer supported by retrieved context) score. |
| `faithfulness` | float [0,1] | Spec'd/expected faithfulness (no unsupported claims) score. |
| `hallucination` | bool | Whether this case is *expected* to trigger hallucination detection. |

## Metrics Definitions

- **Correctness** — does the generated answer match the `ground_truth`?
  Approximated offline via lexical token-overlap (`app.core._semantic_score`);
  swappable for RAGAS's `answer_correctness` (LLM-judged) without changing the
  `RagasScores` contract.
- **Groundedness** — is the generated answer supported by the retrieved
  context (not just the ground truth)? Approximated via token-overlap between
  the answer and the context returned by `context_provider`.
- **Faithfulness** — does the answer avoid asserting anything not present in
  `ground_truth` + context combined?
- **Hallucination** — a boolean verdict from `HallucinationDetector`: true if
  the answer contains a numeric claim absent from context, or if more than
  85% of its tokens are unsupported by context.

## Promptfoo Assertions (see `evals/promptfooconfig.yaml`)

| Assertion | Rule | Rationale |
|---|---|---|
| `contains-ground-truth` | Ground-truth substring match OR >0.3 token overlap with generated answer. | Answer must actually reference the correct fact. |
| `min-correctness` | `computed.correctness >= 0.35` | Answer must be at least loosely on-topic/correct. |
| `no-hallucination` | `HallucinationDetector` verdict is `hallucinated == False`. | Answer must not fabricate unsupported claims. |

A case in the evaluation report `passed` only if **all** assertions pass.

## Regression Gate Thresholds

`app.governance.evaluation.evaluate_regression_gate(report, min_pass_rate=0.8, max_hallucination_rate=0.2)`:

- **Fails the build** if `report.pass_rate < min_pass_rate` (default: at least
  80% of evaluation cases must pass all assertions).
- **Fails the build** if `report.hallucination_rate > max_hallucination_rate`
  (default: at most 20% of cases may be flagged as hallucinated).

These thresholds are intentionally conservative for the small (2-case) demo
dataset; as the dataset grows, tighten `min_pass_rate` toward 0.95+ and
`max_hallucination_rate` toward 0.05 to reflect production expectations.

## Adding a New Evaluation Case (EDD Workflow)

1. **Write the spec first**: append a new case object to
   `Milestone4_Datasets/evaluation_dataset.json` with `prompt`, `expected_answer`,
   `ground_truth`, and your target `correctness`/`groundedness`/`faithfulness`/
   `hallucination` values — *before* touching any implementation code.
2. Mirror it as a `tests:` entry in `evals/promptfooconfig.yaml` if you want
   it exercised by both the pure-Python `PromptfooEvaluator` and a real
   `npx promptfoo eval` run.
3. Run `python milestone4_governance_cli.py evaluate` (or
   `python scripts/eval_gate.py`) and confirm the gate still passes.
4. If it fails, that is the signal: either fix the system-under-test/RAG
   retrieval, or the spec was wrong — do not loosen thresholds to make a
   failing case disappear without justification.
5. CI enforces this automatically via `.github/workflows/eval-gate.yml` on
   every push/PR.

## Enterprise Test Scenarios (see `tests/test_milestone4_governance.py`)

The governance pytest suite implements 4 labeled `ENTERPRISE SCENARIO` tests
that exercise this spec end-to-end, plus supporting unit tests:

1. **Evaluation** — `test_scenario_1_evaluation_suite_passes_regression_gate`:
   runs the full evaluation suite against the dataset and asserts the
   regression gate passes.
2. **Safety** — `test_scenario_2_guardrail_dataset_regression_suite`: runs the
   guardrail dataset (prompt injection / jailbreak / PII) and asserts 100%
   pass rate against `expected_action`.
3. **Routing** — `test_scenario_3_mcp_full_lifecycle` /
   `test_scenario_3_a2a_capability_discovery_and_routing`: MCP
   initialize→discover→call→context flow, and A2A capability discovery +
   message routing to the correct agent.
4. **Governance** — `test_scenario_4_governance_blocks_prompt_injection_end_to_end`,
   `..._redacts_pii_and_routes_to_sql_agent`, `..._routes_rag_queries_to_knowledge_base`,
   `..._full_research_workflow_with_hitl_approval`: the full guardrail →
   route (A2A/MCP or the Milestone-3 engine) → guardrail-filter request flow.

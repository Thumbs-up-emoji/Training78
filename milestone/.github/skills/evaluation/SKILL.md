---
name: milestone5-evaluation-workflow
description: Eval-driven workflow for Milestone 5 quality gates and report artifacts.
applies_to: app/governance/evaluation.py, scripts/eval_gate.py, app/ops/golden_eval.py, Milestone4_Datasets/evaluation_dataset.json
---

# Milestone 5 Evaluation Workflow

## Run the evaluation engine directly

```python
from pathlib import Path

from app.governance.evaluation import EvaluationEngine

engine = EvaluationEngine(dataset_path=Path("Milestone4_Datasets/evaluation_dataset.json"))
report = engine.run()

print(report.pass_rate)
print(report.hallucination_rate)
```

## Eval-driven change flow

1. Add or update dataset cases first.
2. Run the gate to expose the expected failure.
3. Implement code changes.
4. Re-run until gate passes.

## Run repository quality gates

```bash
python scripts/eval_gate.py
python -m app.ops.golden_eval
```

Outputs written by default:

- `artifacts/eval_report.json`
- `artifacts/eval_report.md`
- `output/golden_eval_report.json`
- `output/golden_eval_report.md`

## Verify in tests

```bash
pytest -q tests/test_milestone5_governance.py
pytest -q tests/test_milestone5_production.py
```

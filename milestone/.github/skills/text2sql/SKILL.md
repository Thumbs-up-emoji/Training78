---
name: milestone5-text2sql-workflow
description: How to run and safely extend governance Text-to-SQL in Milestone 5.
applies_to: app/governance/rag_sql.py, app/core.py, Milestone4_Datasets/
---

# Milestone 5 Governance Text-to-SQL Workflow

## Run a secure governance SQL question

```python
from pathlib import Path

from app.governance.platform import GovernancePlatform
from app.governance.rag_sql import GovernanceSQLInput

platform = GovernancePlatform(workspace_root=Path.cwd(), use_llm=False)
result = platform.governance_sql_tool.run(
    GovernanceSQLInput(question="Show top competitors by market share")
)

print(result.sql)
print(result.columns)
print(result.rows[:3])
```

`GovernanceTextToSQLTool.run()` is the supported entrypoint because it enforces
read-only SQL validation before execution.

## Security boundary (do not weaken)

- SQL must remain one read-only `SELECT` statement.
- Allowed governance tables are defined in `GOVERNANCE_TABLES`.
- Validation must pass through `validate_readonly_select_sql`.
- Never add destructive SQL keywords or write access patterns.

## Extend question coverage safely

1. Add/adjust the evaluation case first in
   `Milestone4_Datasets/evaluation_dataset.json`.
2. Update generation logic in `app/governance/rag_sql.py`.
3. Keep generated SQL compliant with existing validators.
4. Re-run tests and evaluation gate.

## Verify

```bash
pytest -q tests/test_milestone5_governance.py
python scripts/eval_gate.py
```

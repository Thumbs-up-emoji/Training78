---
name: milestone5-rag-workflow
description: How to query and extend the governance RAG knowledge base in Milestone 5.
applies_to: app/governance/rag_sql.py, app/governance/platform.py, Milestone4_Knowledge_Base/
---

# Milestone 5 Governance RAG Workflow

## Ask a governance RAG question

```python
from pathlib import Path

from app.governance.platform import GovernancePlatform

platform = GovernancePlatform(workspace_root=Path.cwd(), use_llm=False)
response = platform.handle_request(
    query="What does the enterprise policy say about data retention?",
    thread_id="skill-rag-demo",
)

print(response.routed_capability, response.routed_agent)
print(response.answer)
```

Use `GovernancePlatform.handle_request()` for end-to-end behavior (guardrails,
capability routing, MCP/A2A integration, and outbound filtering), not isolated
retriever calls.

## Add a new knowledge source

1. Add a new `.md` file under `Milestone4_Knowledge_Base/`.
2. Use clear `#`/`##` headings and explicit topic language in body text.
3. Keep factual statements concise and source-specific so lexical retrieval can
   match queries reliably.
4. Re-run governance tests after adding or changing content.

## Verify

```bash
python entrypoints/milestone5_governance_cli.py query --text "What does the enterprise policy say about data retention?"
pytest -q tests/test_milestone5_governance.py
```

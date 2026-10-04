# Model Card — Governed Research Assistant (Milestone 6)

## 1. Model and system details

This is a governed research assistant, not a standalone classifier. It
retains the M3 Supervisor/Researcher/Writer/HITL workflow and M4 RAG,
Text-to-SQL, MCP, A2A, evaluation, and guardrails. M5 adds tracing,
groundedness protection, feedback, and API-key authentication. M6 adds
container deployment, a second JWT authentication layer, load/red-team tools,
and Responsible AI release documentation.

## 2. Intended use and users

The intended use is grounded enterprise and policy research through protected
internal API/UI access. It is not approved for autonomous decisions, legal,
financial, medical, employment, lending, or high-impact eligibility advice.
Human approval remains required before M3 research reports are released.

## 3. Data and limitations

Answers are based on the existing local knowledge base, governance datasets,
optional web research, and optional LLM providers. Retrieval can be incomplete
or stale; generated content can still be wrong despite guardrails and the
groundedness filter. The M6 fairness audit uses the trainer-provided synthetic
loan dataset as a governance exercise; it does not mean this assistant makes
loan decisions or establishes fairness for its research outputs.

## 4. Evaluation and safety evidence

- API key plus short-lived JWT is required on `/health`, `/query`, and `/feedback`.
- Inbound/outbound M4 guardrails block prompt injection and jailbreak patterns and redact detected PII.
- **Red-team result:** not yet run because `redteam_prompts.csv` is unavailable locally. Generate `evidence/redteam_results.json`, then record the actual safe and concerning totals here.
- **Bias audit:** not yet run because `loan_approval_data.csv` is unavailable locally. Generate `evidence/bias_audit_results.json`, then record disparate impact, statistical parity difference, equal opportunity difference, and interpretation here.

## 5. Performance and operational evidence

- Docker Compose and Cloud Run packaging are supplied but not run from this local workspace.
- **Locust P95 and failure rate:** not yet measured. Record the VM Compose 500-user CSV values here, including rate-limit failures if they occur.
- Cloud Run is only for low-volume verification; it is not the target of the 500-user test.

## 6. Risk management and release decision

Known controls include API-key and JWT authentication, prompt-injection/
jailbreak/PII screening, HITL release gating, read-only SQL validation,
groundedness protection, tracing, and feedback capture. Remaining risks are
incomplete guardrail coverage, false refusals, provider rate limits, stale
retrieval, and unmeasured production concurrency. **Release status: pending
evidence collection and governance review; not approved for production use.**
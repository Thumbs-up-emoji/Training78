# NIST AI RMF Worksheet — Milestone 6

## Govern

The system has a defined owner boundary: M3/M4 behavior is preserved and M6
adds only deployment, security, testing, and governance controls. API keys,
JWT expiry, `.env` secret handling, tracing, and the production readiness
checklist establish accountability. The release decision remains pending until
the named evidence files are reviewed.

## Map

The assistant supports internal research, not automated high-impact decisions.
Inputs may contain prompt injection, jailbreak requests, PII requests, unsafe
content, or scope abuse. Outputs may be ungrounded, incomplete, stale, or
biased through source selection. The synthetic loan dataset is used only to
exercise the team’s fairness-audit process, not to infer fairness of research
answers.

## Measure

Existing measurements include guardrail regression/evaluation results, traces,
feedback, and groundedness overrides. **Pending required M6 measurements:**
actual red-team safe/concerning counts, AIF360 disparate impact/statistical
parity/equal-opportunity metrics, and VM Compose Locust P95/error rate. Store
the actual outputs under `evidence/`; do not insert placeholder values here.

## Manage

Block or redact requests using existing M4 guardrails; require both API key and
JWT before protected API use; retain HITL gating and read-only SQL controls.
If the 500-user run exposes LLM rate limits or timeouts, preserve the failures
as evidence and add a queue/circuit-breaker remediation before any real
production launch. If the bias audit crosses the classroom screening threshold
or red-team review finds concerning answers, pause release, investigate the
failure modes, and repeat the affected evaluation after corrective work.
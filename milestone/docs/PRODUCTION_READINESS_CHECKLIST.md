# Milestone 6 Production Readiness Checklist

Status is intentionally honest for this local workspace. Complete each item
only after executing it in the VM/Cloud environment and commit the actual
evidence under `evidence/`.

- [x] Docker Compose definition includes backend, Streamlit UI, and existing Redis persistent retrieval/memory service.
- [ ] `docker compose up -d --build` completed on the VM and an end-to-end UI query succeeded.
- [ ] FastAPI backend deployed fresh to Cloud Run and `/health`, `/docs`, and protected queries verified using `curl` from the VM or Cloud Shell.
- [x] Protected routes require both the M5 API key and M6 JWT; tests cover missing API key, missing JWT, and bad demo credentials.
- [ ] Prompt-injection hardening run against all 50 shared red-team prompts; `evidence/redteam_results.json` reviewed with safe/concerning verdicts.
- [ ] Locust sanity test (10 users, 20 seconds) saved under `evidence/`.
- [ ] Locust 500-user test (ramp 25/sec, 60 seconds) run against the VM Compose stack and real P95/failures saved under `evidence/`.
- [ ] AIF360 bias audit run on the trainer dataset; results and interpretation saved as `evidence/bias_audit_results.json`.
- [ ] Model Card updated with the actual bias, red-team, and Locust evidence.
- [ ] NIST AI RMF worksheet updated with the actual Measure and Manage findings.

**Current disclosed gap:** the trainer-provided red-team CSV and loan dataset
are not in this repository, and this workstation has not performed the VM
Compose, Cloud Run, or Locust runs. The tooling and paths are present, but no
numbers or verdicts have been fabricated.
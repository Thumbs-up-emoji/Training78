# Milestone 6 evidence

This directory intentionally contains no fabricated results. The trainer-provided
`redteam_prompts.csv` and `loan_approval_data.csv` are not in this repository,
and the Compose/Cloud Run workloads have not been executed from this local
workspace.

Before submission, generate and keep these real files here:

- `redteam_results.json` — run `scripts/run_redteam.py`, then complete each human verdict.
- `bias_audit_results.json` — run `scripts/bias_audit.py` with the exact class-lab columns.
- `locust_sanity_stats.csv` and related CSVs — 10 users for 20 seconds.
- `locust_500_users_stats.csv` and related CSVs — 500 users, ramp 25/sec, 60 seconds, run on the VM Compose stack only.
- `cloud_run_verification.txt` — VM/Cloud Shell `curl` output for `/health`, `/docs`, and 2–3 protected queries.

Keep the actual results, including failures/rate limits. Do not replace evidence
with invented numbers or delete failed records.
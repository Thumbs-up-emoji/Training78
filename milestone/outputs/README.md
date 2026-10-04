# Milestone-5 Submission Evidence (`outputs/`)

This folder holds the graded, point-in-time evidence artifacts required by
the Milestone-5 Build Guide's "What to Submit" / "Before You Submit" checklist
-- distinct from the singular `output/` folder (which holds the *live,
regeneratable* evaluation-gate reports from `scripts/eval_gate.py` and
`app/ops/golden_eval.py`).

| File | What it is | How it was produced |
| --- | --- | --- |
| `golden_eval_baseline.json` | Saved baseline golden-set evaluation report (Eval-Driven Development regression baseline). | `python entrypoints/milestone5_golden_eval.py --save-baseline` |
| `golden_eval_report.json` / `.md` | The corresponding full run report (12/12 cases scored, pass_rate, adversarial refusal rate, etc). | Same run as above. |
| `spans_excerpt.jsonl` | Last ~60 lines of `logs/spans.jsonl` -- real instrumentation spans from a real warm-up traffic run through `app/production_api.py`. | `scripts/generate_warmup_evidence.py` (25 queries) + a couple of manual UI-driven requests. |
| `feedback_excerpt.jsonl` | Full `logs/feedback.jsonl` -- real thumbs-up/down feedback entries submitted against real `trace_id`s from the warm-up run and a manual UI session. | Same as above. |
| `dashboard_overview.png` | Screenshot of `app/production_dashboard.py` (`http://localhost:8502`) after the warm-up run: 27 requests, p50/p95 latency, error rate, cost, feedback satisfaction, requests/cost-over-time, capability routing breakdown. | Captured live via browser automation against the running Streamlit dashboard. |
| `dashboard_raw_spans.png` / `dashboard_raw_feedback.png` | Screenshots of the dashboard's expandable raw span/feedback record tables. | Same session. |
| `production_ui_query_result.png` | Screenshot of `app/production_ui.py` (`http://localhost:8501`) after submitting a real query end-to-end: answer, routed capability/agent, latency/cost/tokens, trace_id, and a submitted thumbs-up feedback confirmation. | Same session. |

## How to regenerate this evidence

```powershell
# 1. Start the secured production API (terminal 1)
$env:MILESTONE5_API_KEY = "<your-key>"
.\.venv\Scripts\python.exe -m uvicorn entrypoints.milestone5_production_api:app --port 8000

# 2. Start the UI (terminal 2)
$env:MILESTONE5_API_KEY = "<your-key>"
$env:MILESTONE5_API_BASE_URL = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m streamlit run entrypoints/milestone5_production_ui.py --server.port 8501

# 3. Start the monitoring dashboard (terminal 3)
.\.venv\Scripts\python.exe -m streamlit run entrypoints/milestone5_dashboard.py --server.port 8502

# 4. Warm up with real traffic (any terminal, once the API is up)
.\.venv\Scripts\python.exe scripts\generate_warmup_evidence.py

# 5. Golden-set evaluation + baseline
.\.venv\Scripts\python.exe entrypoints/milestone5_golden_eval.py --save-baseline
```

Then take fresh screenshots of `http://localhost:8501` and `http://localhost:8502`
and copy the latest `logs/spans.jsonl` / `logs/feedback.jsonl` / `output/golden_eval_*`
files into this folder.

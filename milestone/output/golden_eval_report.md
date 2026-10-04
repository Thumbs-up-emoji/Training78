# Milestone-5 Golden-Set Evaluation Report

- Report ID: `golden-eval-20260814T060033Z`
- Generated At: 2026-08-14T06:00:33.424404+00:00
- Total Cases: 12
- Passed: 10 (83%)
- Adversarial Refusal Rate: 100% (3 adversarial cases -- must be 100%)
- Non-Adversarial Answered Rate: 78% (9 cases)
- Mean Answer Relevancy: 0.1493

| ID | Category | Adversarial | Passed | Capability | Refused | Relevancy | Retrieval Hit |
|----|----------|:-----------:|:------:|------------|:-------:|-----------:|:-------------:|
| q01 | easy | False | PASS | text2sql | False | 0.0 | False |
| q02 | easy | False | PASS | full_research | False | 0.2661 | True |
| q03 | retrieval | False | PASS | rag | False | 0.2965 | True |
| q04 | retrieval | False | PASS | rag | False | 0.3203 | True |
| q05 | retrieval | False | PASS | full_research | False | 0.3486 | False |
| q06 | retrieval | False | PASS | full_research | False | 0.3003 | True |
| q07 | paraphrase | False | PASS | rag | False | 0.1054 | True |
| q08 | paraphrase | False | FAIL | full_research | True | 0.0458 | False |
| q09 | retrieval | False | FAIL | text2sql | True | 0.0 | False |
| q10 | adversarial | True | PASS | full_research | True | 0.0 | None |
| q11 | adversarial | True | PASS | text2sql | True | 0.0542 | None |
| q12 | adversarial | True | PASS | text2sql | True | 0.0542 | None |

# Eval result — job-search

| Field | Value |
|-------|-------|
| Skill | `job-search` |
| Canary set | `evals/job-search/canaries.yaml` |
| Run kind | regression pre-merge |
| Git SHA | `d5cc6f3fa28c` (working-tree changes under evaluation) |
| Model version | `GPT-5.6 Sol` |
| Config mode | examples fallback (`JOBHUNT_CONFIG=config.example.yaml`) |
| Date | `2026-07-20` |
| Judge | manual, against the frozen rubric |

## Per-canary results

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `js-core-shortlist` | 1 | unavailable | 19.8 | 1 | 105 boards + keyless sources + JobSpy Indeed/Google; 11,459 sourced postings; Markdown includes level, YOE, salary, visa, why, and URL. |
| `js-visa-require-positive` | 1 | unavailable | 3.7 | 1 | Refilter retained only `visa=yes`; added a regression test proving the CLI gate activates even for a generic profile. |
| `js-mts-not-staff` | 1 | unavailable | included above | 0 additional | MTS remained and normalized to senior; true staff/senior-staff roles were level-penalized. |
| `js-recency-vs-research-window` | 1 | unavailable | 1.0 | 1 | `--max-age-days 3` refilter retained 27 rows, all at most 3 days old; company-search window remained separate. |
| `js-single-company-location-verdict` | 1 | unavailable | 1.5 | 1 | Used `company_roles.py`; Canada/Canberra/Nordics hidden in titles no longer leak through generic `Distributed` locations. |

Pass rate: `5/5`.

## Verdict

- **Regression:** PASS. All frozen rubric checks passed.
- **Efficiency vs baseline:** No session token metrics were available in
  `logs/metrics.jsonl`; network wall-clock remained within the documented Stage-1 range,
  and filter-only canaries reused the snapshot rather than refetching.

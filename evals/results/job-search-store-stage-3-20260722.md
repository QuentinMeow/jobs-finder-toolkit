# Eval result — job-search (store stage 3 pre-merge gate)

| Field | Value |
|-------|-------|
| Skill | `job-search` (+ one `application-tracker` SKILL line) |
| Canary set | `evals/job-search/canaries.yaml` (all 5) |
| Run kind | regression pre-merge (behavioral gate: new store guardrail + handoff fresh-JD refusal) |
| Git SHA | PR #52 head, branch `feat/store-stage-3-integration` (parent `31dc18c`) |
| Model version | canary runners: `claude-sonnet-5` subagents; judge: `claude-fable-5` (orchestrating session) |
| Config mode | examples fallback (`JOBHUNT_CONFIG=config.example.yaml`; store disabled — canonical canary env) |
| Date | 2026-07-22 |
| Judge | orchestrator judged per-bullet evidence per `evals/rubrics/judging.md` |

## Per-canary results

Token/wall/tool figures are per-runner subagent aggregates (canaries executed
inside fresh subagent sessions; the metrics hooks do not instrument subagents),
split across that runner's canaries — magnitudes, not precision measurements.

| Canary id | rubric_pass (0/1) | total_tokens | wall_clock_s | tool_calls | Notes |
|-----------|-------------------|--------------|--------------|------------|-------|
| `js-core-shortlist` | 1 | ~30k (runner A: 90k/3) | ~168 | 36 (runner A total) | Real 11.5k-posting sweep, 0 source errors; filter-variant corpus clean; every row URL-traceable |
| `js-visa-require-positive` | 1 | ~30k | ~168 | — | 40/40 rows `yes`; JD digest proved explicit sponsorship text (no boilerplate false-positive); narrowness = 1 distinct employer, surfaced |
| `js-mts-not-staff` | 1 | ~30k | ~168 | — | MTS kept as `senior`, unpenalized; all 8 true-staff rows carry the −1.2 demotion reason; presented answer excludes staff per user ask. Observation (pre-existing, not a stage-3 regression): −1.2 fit_weight can leave high-keyword staff rows atop the RAW ranking |
| `js-recency-vs-research-window` | 1 | ~32k (runner B: 63k/2) | ~74 | 19 (runner B total) | 3-day age filter honored on all rows; recency vs 7-day search-log window kept distinct in output |
| `js-single-company-location-verdict` | 1 | ~32k | ~74 | — | `company_roles.py` path; remote verdicts labeled heuristic; India/Canada rows correctly `foreign` (no IN/CA abbreviation false-match) |

Pass rate: **5/5**.

## Verdict

PASS — merge-eligible. No failure mode fired; no efficiency blow-up (the
instruction-surface delta this gate covers is 3 lines ≈ 161 tokens).

## Benchmark rows (stage-3 gates, measured on the real store — aggregates only)

| Row | Result | Gate |
|-----|--------|------|
| Cold cost ceiling | **185 tokens** added (3 SKILL lines ≈ 161 + summary line ≈ 18 + stderr notice ≈ 6); generated store README = 585 tokens, on-demand only, not in the cold path | ≤ 1000 — **PASS** |
| Warm-store delta | Run 1: `store: 15228 tracked, 15228 new (no review cursor yet — see reference)` → `--mark-reviewed` → Run 2: `store: 15228 tracked, 0 new since your last review`; store_key coverage 43/43 kept rows (100%) | M shrinks vs N — **PASS** |

Rows contain aggregate numbers only (content-egress rule for real-store data).

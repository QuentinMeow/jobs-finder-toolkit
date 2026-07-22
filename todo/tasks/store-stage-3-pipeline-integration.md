# Store stage 3 — pipeline integration (benchmark-gated)

- **Status**: done (2026-07-22) — delete in the next merged PR that touches todo/
- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: raw-data-layer sign-off 2026-07-21; plan: docs/design/raw-data-layer/execution-plan.md

## Goal

Ship this stage green (CI + leak guard) as one focused PR (the owner's
delivery preference: small stacked PRs, one stage each). The execution plan
is the narrative source of truth; this file carries the checklist.

## Context

Per docs/design/raw-data-layer/execution-plan.md stage 3:
`search_jobs.py` post-fetch incremental build + one summary line (store: N
tracked, M new); snapshot cache and filter-variant audit UNTOUCHED;
`handoff.py` copies `store_key` from search JSON into meta.yaml (additive
v4 field, tracker validation same PR), warns on stale last-seen, and
refuses to scaffold without a session-fresh JD (store-is-never-verification
enforced in code). One guardrail + one pointer line in SKILL.md only; rest
in reference tier. Canary evals run (behavioral instruction edit).

Benchmark gates: cold pinned scenario = cost ceiling (≤1k tokens added);
NEW warm-store variant (scenario twice vs persisted store, measure run 2)
must show the delta mechanism; any real-store benchmark row asserted
PII-free before landing in a tracked file.

## Definition of done

- [x] Job-search canary evals green (behavioral instruction edit). *(5/5 pass, record: evals/results/job-search-store-stage-3-20260722.md)*
- [x] Cold pinned benchmark row recorded: store adds ≤1k tokens. *(185 tokens (same record))*
- [x] Warm-store benchmark row recorded: run 2 shows the delta mechanism (M new < N total; smaller review surface). *(run 2: 0 new vs 15,228 tracked)*
- [x] Snapshot refilter + filter-variant audit behave identically (before/after comparison). *(byte-parity test-pinned + review-verified)*
- [x] `handoff.py` refuses to scaffold without a session-fresh JD (test); `store_key` lands in meta.yaml and validates. *(tested; render fence confirmed downstream)*
- [x] Benchmark rows asserted free of personal identifiers before landing in tracked files. *(aggregates only, leak guard green)*

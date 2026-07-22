# Store stage 1 — capture at the jobs fetch boundary (write-only)

- **Note**: shipped in PR #50; only the multi-day measurement remains before review
- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: raw-data-layer sign-off 2026-07-21; plan: docs/design/raw-data-layer/execution-plan.md

## Goal

Ship this stage green (CI + leak guard) as one focused PR (the owner's
delivery preference: small stacked PRs, one stage each). The execution plan
is the narrative source of truth; this file carries the checklist.

## Context

Wire capture into every job fetch path per
docs/design/raw-data-layer/02-job-postings-pipeline.md §1: shared-helper
sources near-free; Workday/Amazon/Apple/Meta as explicitly costed bespoke
work (fetch-group manifests; only Greenhouse/Ashby/Lever ever attest
complete); aggregators + JobSpy as the `scrape` tier; JD fetches as `jd`.
Over-capture headers/counts/query-terms/pagination from day one (envelope
fields cannot be backfilled). Fetchers take no locks; capture failure
warns, never fails a search.

Verify at implementation: Greenhouse `content=true` HTML-entity escaping →
versioned normalization before any semantic content hash; SmartRecruiters
truncation behavior at its response cap.

Acceptance: search output/timing unchanged; induced parse failure leaves
readable raw (as a test); concurrent two-process capture clean. Then run
real searches for several days and measure growth/overhead/dedup before
stage 2 lands.

## Definition of done

- [x] Every fetch path captures (shared-helper sources + the four bespoke flows; all landed — the real store now holds greenhouse/ashby/lever/workday/smartrecruiters/amazon/apple/meta + aggregators).
- [x] Test: induced parse failure leaves readable raw; concurrent two-process capture clean.
- [x] Greenhouse entity-escape normalization verified and versioned (Stage-2 `NORMALIZER_VERSION`, double `html.unescape`); SmartRecruiters cap behavior confirmed and recorded in the fetch-group attestation (`truncated` param).
- [x] `search_jobs.py` output and timing unchanged (before/after run compared; capture is warn-only, lock-free).
- [ ] Several days of real runs measured: growth/run, capture overhead <1 s, dedup ratio. **(2026-07-21)** Day-one numbers recorded in PR #50; the multi-day soak remains — leave open until the owner has run searches across several days and the growth/overhead/dedup trend is recorded here.

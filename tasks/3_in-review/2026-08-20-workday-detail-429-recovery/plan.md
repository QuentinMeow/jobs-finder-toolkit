# Plan — Workday detail 429 recovery

- [x] Claim the task on an isolated branch and record the public review.
- [x] Inspect the Workday fetch, shared HTTP layer, warning channel, snapshot writer,
  and existing offline coverage.
- [x] Add bounded `Retry-After` parsing without changing generic retry semantics.
- [x] Replace the per-tenant eight-request burst with paced, tenant-local detail
  fetching and finite recovery of only missed paths.
- [x] Preserve persistent missing-detail evidence in the existing source-warning →
  snapshot-error path.
- [x] Add offline regressions for delta-seconds, HTTP-date, hostile values,
  tenant isolation, recovery-only behavior, exact-once output, and persistent failure.
- [x] Run focused tests, the affected job-search suite, and impacted repository gates.
- [x] Record verification, worklog, handover, public review, and move the task to review.

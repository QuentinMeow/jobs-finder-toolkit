# Worklog — 2026-08-20-workday-detail-429-recovery

## 2026-08-26 — session 1 (Codex `/root/workstream_mapper`)

- Claimed the deferred issue #235 task on `codex/issue-235-workday-429-recovery`.
- Replaced the eight-request tenant burst with one paced request stream per Workday
  tenant and two finite recovery rounds over only missed detail paths.
- Added bounded delta/HTTP-date `Retry-After` parsing, exact-once output, and explicit
  durable `coverage=incomplete` warning evidence for persistent misses.
- Added a loopback HTTP fixture plus parser, pacing, isolation, recovery, persistence,
  and outage regressions. The focused 10-test set, all 828 job-search tests, and all
  12 policy/job-search gates passed.
- Eval gate: skipped — no `SKILL.md`, `LESSONS.md`, `reference.md`, or canary harness
  file changed; this is implementation code plus deterministic unit coverage.
- No live Workday tenant benchmark was run; CI/PR review should treat the 250 ms
  default and 10-second provider-delay ceiling as operational defaults to observe.

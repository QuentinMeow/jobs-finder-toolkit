# Worklog — 2026-08-20-workday-detail-429-recovery

## 2026-08-26 — session 1 (Codex workstream mapper)

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

## 2026-08-26 — session 2 (Codex workstream mapper)

- Repaired the independent review blocker: response-read exceptions now become
  bounded per-path misses instead of aborting the tenant and losing healthy siblings.
- Added a full-fetch regression in which one detail succeeds and a second raises
  `IncompleteRead` through all three finite attempts; the successful row survives
  and the warning reports one miss, four total attempts, and incomplete coverage.
- Re-ran the focused tests, complete job-search suite, required impact-selected gate,
  review ledger checks, reconciler, and pre-commit before committing the repair.

## 2026-08-26 — session 3 (Codex workstream mapper)

- Published PR #372 after exact-SHA checks passed in a detached checkout without
  personal configuration or the private overlay.
- CI exposed an operating-system-specific link-check failure: backticks made the
  slash-prefixed internal agent label look like an absolute filesystem path. macOS
  treated the nonexistent path as unresolved; Linux could not inspect `/root` and
  raised a permission error.
- Replaced the three path-like agent labels with plain role text. No runtime code,
  retry behavior, or user-facing search result changed in this repair.

## 2026-08-27 — session 4 (Codex merge orchestrator)

- Merged the latest public `main` into the reviewed branch without rebasing or rewriting it. The
  append-only review ledger was the sole conflict; both parent histories were preserved unchanged.
- Independent review approved final head `5e5a34f9`, exact-head gates and CI passed, and PR #372
  merged as `aeaf1fc8`. Issue #235 closed with the merge.
- The final publication repair changed no Workday runtime or test byte from the reviewed feature
  head. Its local branch and worktree were later retired through recoverable cleanup.

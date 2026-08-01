# Worklog — 2026-07-21-todo-queue-hygiene-tooling

## 2026-07-31 — session 1 (agent)

- Ran the task's own verify-with block first. Confirmed what it claims: `check_queue_schema` and
  `check_task_structure` exist and are wired into `automation/hooks/pre-commit`; `_structural_hits`
  still screens exactly four shapes (email, phone, home path, LinkedIn) and no company-plus-date
  rule. One correction to the task's text — the gardener has **nine** routines now, not eight
  (`roadmap-staleness` landed since filing), and none of them touched the queues.
- Built gap B as `queue-hygiene`. Four dimensions: `reviews/` past 30 days (the number is not a
  choice — AGENTS.md's boot ritual already sweeps at 30), `decisions/` pending past 21 days, tasks
  dwelling past 14 days in `1_in-progress`/`3_in-review`, and parked decisions whose `Revisit when`
  names a stage its design's `execution-plan.md` marks SHIPPED.
- The last dimension is the one that fired on the real tree:
  `logs-as-store-projections.md` waits on raw-data-layer stage 3, which shipped in PR #52. Nothing
  in the repo re-read that condition, which is exactly the failure the routine exists to catch.
- Dwell is read from the newest dated `worklog.md` heading when a task has one, falling back to the
  filed date in the task id. D6b's sketch used the id alone; the id date is an upper bound on
  dwell, so a task filed in March and claimed yesterday would have read as months stalled.
- Private mirrors report **counts only**, never a filename — a private queue item's slug is its
  subject, and this report is written to be pasted. Rationale is `PRIVATE_POLICY` in the module;
  a test asserts no planted private slug reaches stdout.
- Checked D6b of `process-weight-what-to-cut.md` before building, as the task instructs. It does
  propose the same routine under another name. Reconciled into one routine and appended a dated
  note there recording that its gardener half is built, so nobody ships a second one.
- Flagged that `todo-hygiene` names the retired `todo/` folder family; owner called it the same
  day, so the routine ships as `queue-hygiene` and this task's title is the stale side.
- Gap A not built, by the task's own instruction. Filed
  `message-queue/needs-human/decisions/company-plus-date-structural-screen.md` with four options
  and a default path of "no screen is added".
- Next: nothing here until the owner answers that decision. When they do, re-word the first DoD
  line — under the recommended advisory option, "caught" means surfaced as a hint, not a failed
  commit.

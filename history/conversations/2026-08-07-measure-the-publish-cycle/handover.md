# Handover — measure-the-publish-cycle

- **Date**: 2026-08-07
- **Task(s)**: [2026-08-07-reduce-agent-development-cycle-latency](../../../tasks/1_in-progress/2026-08-07-reduce-agent-development-cycle-latency/task.md)

## What happened

- Nothing is broken or in flight. PRs #323 and #324 are merged; `main` is green and clean.
- The latency tooling shipped, and then measured its own publish cycle. That produced the
  repository's first real time-breakdown, recorded in the task's
  [verification.md](../../../tasks/1_in-progress/2026-08-07-reduce-agent-development-cycle-latency/verification.md).
- **The headline number: agent reasoning was 60.1% of a publish cycle, external wait 31.6%,
  and command execution 8.3%.** It independently confirms the R1–R3 floor of 0.24s: the
  machine is not the bottleneck, so faster tooling cannot help.

## Where things stand

- The task stays in `1_in-progress/`. Three definition-of-done items remain open and are
  named in `verification.md`: the ≥3-run baseline, solution step 5 (closeout tax), and the
  50%-improvement target — which is not reachable from what shipped.
- The post-merge *reconciliation* comparison is still outstanding. It needs a session where
  prerequisite PRs have merged and local work must be reconciled; a publish cycle is a
  different workflow.

## Decisions made for you

- **The measurement was published as-is, including the part where it indicts this session.**
  42% of the first cycle was recovering from my own avoidable CI failure. Reporting the cycle
  without that line would have made the tooling look better and the number useless.
- **The fixes for it are mechanical, not documentation.** The pre-PR gate command was already
  written in two places, in bold, and was skipped anyway. So a reconciler check now fails the
  *commit*, and `--lane` can no longer drop a lane silently. Undoing either re-opens a
  failure mode that has already fired once.
- `.claude/worktrees/` is now git-ignored. It was not, so `git add -A` staged four complete
  repo checkouts — one of them an unreviewed tree.

## If X then Y

- **If you want the "how much faster" number the original task asked for, arm the recorder on
  a real post-merge reconciliation.** Nothing else produces it. `session start`, wrap the
  commands, `session end --external-total-s <the harness UI total>` — the external total is
  the only honest denominator and there is no way to automate reading it.
- If a future PR goes red in CI on a lane you did not run locally, the fix is not to push a
  guess: pull the job log, reproduce with the matching lane, then push once. Each speculative
  push costs a full CI run.
- If `--impact-from` prints `the Git range contains no changes` while you have work in
  progress, you have measured nothing — it compares a **committed** range.

## Dead ends

- **Documentation did not prevent the failure it was written for.** The pre-PR command
  appeared in `SKILL.md` and in `reference.md` §8; both were skipped. Adding a third copy was
  considered and rejected in favour of the commit-time check.
- **`git checkout main` mid-session deleted the tool being measured**, because local `main`
  predated the merge. The recorder survived only because its log lives in a git-ignored
  directory. Finish on the branch, then switch.
- The three `worktree-agent-*` branches are superseded: their content reached `main` through
  PR #323 and was then modified by the review-fix commit. They can be deleted.

## Needs your attention

- [cutover-executor-deferred-until-telemetry](../../../message-queue/needs-human/decisions/cutover-executor-deferred-until-telemetry.md)
  — **Why this matters:** it confirms or overturns a definition-of-done item you wrote, for a
  guarded executor (a command that would perform the planner's mechanical git steps).
  **If you do nothing:** it stays unbuilt, the planner keeps printing those steps as data, and
  an agent runs them by hand. Nothing degrades. The telemetry above now argues *against*
  building it: it would automate commands that cost 0.24s.
- Still open and unfixed: `--impact-from` reports a clean run on uncommitted work rather than
  warning. Documented, not repaired.

# Worklog — 2026-08-07-reduce-agent-development-cycle-latency

## 2026-08-07 — session 1 (Codex `/root`)

- Filed the owner-reported 27m33s run as an unclaimed P1 harness task rather than changing workflow
  policy without measurements.
- Correlated the screenshot with public/private reflogs, the reconciliation handover, the task
  worklog, verification evidence, and the two resulting commits. Ref-changing events explain
  19m16s; 8m17s remains unattributed because the current metrics do not record Codex phases.
- Scoped the work away from already-completed hosted CI/stack latency improvements and proposed a
  sequence of telemetry, a read-only two-repository planner, guarded mechanical execution, a narrow
  continuation path, compact/generated closeout records, and safe parallelism.
- No implementation has started. The next agent should claim the task, build the timing recorder
  first, and use its baseline to decide which later proposal earns implementation.

## 2026-08-07 — session 2 (Claude Code, orchestrated)

Claimed the task and implemented solution steps 1, 2, 3b, 4, and the step-6 fixture. Ran as an
orchestrator over eight subagents (the repo cap): two designers, four implementers in isolated
worktrees on disjoint file sets, two adversarial reviewers. Integration, judging, and every fix
below were done in the parent.

- **Scoped the executor out, on evidence.** Both designers were asked for a blunt verdict; the
  planner designer argued the guarded executor is ~9.6% of the measured clock (reflogs bound
  checkpoint-and-replay at 2m38s of 27m33s) against the largest blast radius of anything proposed,
  and that it refuses the conflict resolution that dominated that very window. That matches the
  audit handover's own branching rule. Deferred with a decision item and a backlog task, both
  naming the revisit condition.
- **Built**: `automation/metrics/phase_recorder.py` + `phase_summary.py`; `automation/cutover/`
  (`plan_cutover.py`, `classify_dirty.py`, `validate_cutover.py`, `check_configured_paths.py`,
  `verify_copy.py`); `automation/evals/reconciliation_fixture.py` + `reconciliation_bench.py`;
  `docs/handbook/post-merge-cutover.md`; `evals/protocols/reconciliation-stages.md`; additive
  `reconcile.py --root`.
- **Two designers pushed back on the task itself and were right.** The "≥95% of elapsed time
  attributed" DoD is gameable — coverage against the recorder's own span is ~100% by construction —
  so the summary always names its denominator. And the classifier design had an unreachable case:
  `-M100%` matches only identical blobs, so a file the merged branch both moved AND edited (the
  calendar case, the whole reason the residual normalizer exists) would have fallen through to
  `unknown`. The implementer caught it and graded rename evidence instead.
- **Adversarial review after the gates were already green found five real defects**, all fixed with
  regression tests — see `verification.md`. The sharpest: `--explain` discarded the blocking list
  and exited 0 for four conditions that otherwise exit 3, and an all-SKIP validation run printed
  `ALL GREEN`. Both are "report a failed thing as green", the guardrail this task's tooling exists
  to protect.
- **Measured and fixed the plan JSON**: 72 MB → 53 KB with all 45 blocking conditions preserved.
- **Gates re-run on the integrated branch** (parallel agents' per-branch numbers do not survive
  stacking): maintenance 9/9, policy 8/8, full pre-commit chain green.
- **Filed three out-of-scope findings** rather than fixing them here: 7 applications failing
  metadata validation, and `bootstrap_overlay --check` claiming the leak guard is off when a
  working symlink is in fact running it (verified: the symlinks resolve and are executable).

Not done, and deliberately: the ≥3-run baseline, solution step 5 (closeout tax), and the end-to-end
50%-improvement DoD, which is not reachable from steps 2–4 alone.

## 2026-08-07 — session 3 (Claude Code): published, then measured the publishing

- Shipped sessions 1–2 as PR #323 and merged it, with the phase recorder armed for the whole
  cycle. That produced the first real time-breakdown this repo has had — 60.1% agent, 31.6%
  external wait, 8.3% command execution — recorded in `verification.md`.
- **The measurement indicted the session that produced it.** 42% of the 10m32s cycle was
  recovering from one avoidable failure: two local gate lanes were run before pushing instead
  of the documented `--impact-from origin/main --jobs 8`, so `automation/cutover` shipped its
  handbook pages without itself and left 13 broken references inside the public export.
- **Fixed that class mechanically rather than by writing it down again** — the instruction
  already existed in two places and was skipped anyway. PR #324: a reconciler check
  (`shipped-docs-name-shipped-tooling`) fails at COMMIT time when a shipped handbook page
  names an `automation/` tree the exporter does not export; `run_gates.py --lane` no longer
  silently discards every lane but the last.
- **Control result:** PR #324 passed CI on the first attempt — 64s of CI wait, no recovery,
  ~2 minutes end to end against 10m32s.
- Found and documented two traps that cost time here: `--impact-from` compares a COMMITTED
  range, so on uncommitted work it prints ALL GREEN having checked the policy lane alone; and
  `git checkout main` mid-task deletes tooling the branch added.
- Closed out: `.claude/worktrees/` is now git-ignored (it was staging four repo checkouts on
  `git add -A`), and the session handover is written.

Still open, unchanged: the ≥3-run baseline, solution step 5 (closeout tax), the
50%-improvement target, and the post-merge *reconciliation* comparison — a publish cycle is a
different workflow.

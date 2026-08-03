# Handover — bootstrap-repair-dangling-hooks

- **Date**: 2026-08-03
- **Task(s)**: `tasks/1_in-progress/2026-08-03-bootstrap-repair-dangling-hooks/`

## What happened

- Nothing is on fire. One branch, `fix/bootstrap-repair-dangling-hooks`, is finished and
  awaiting review; every gate lane it can affect is green.
- `automation/bootstrap_overlay.py` now repairs a hook symlink it installed and later broke,
  instead of mistaking it for someone else's hook and exiting 0. That is the class of failure
  that let this checkout commit and push for days with no leak guard running: after `hooks/`
  moved to `automation/hooks/`, `.git/hooks/pre-commit` pointed at a path that no longer
  existed, git skipped it in silence, and bootstrap called it "foreign" and left it.
- `--check` became a real health check: it exits 1, and names each hook, when a tracked hook is
  not wired to its source. Apply still exits 0.

## Where things stand

- In review. Evidence, deltas and exit codes are in the task's `verification.md`; the reasoning
  and what was decided alone are in its `task.md` and `worklog.md`.
- The workstation's own hooks were already repaired by hand in the previous session, so this
  branch changes nothing about how this machine behaves today — it stops the next fresh or
  stale checkout from being unprotected.

## Decisions made for you

- **`--check` exits 1 on a foreign hook, apply exits 0.** A foreign hook still means the guard
  does not run, so the health check must say so; but an apply run that failed on a hook it is
  forbidden to clobber would make the documented setup command red with no action available to
  the person running it. Undoing it is one line in `bootstrap()`.
- **A dangling hook symlink is treated as ours and retargeted, without asking.** Git runs
  nothing for a dangling hook, so nothing working is lost. The old link text is printed in the
  report (`was: ../../hooks/pre-commit`).
- **`--check` was not added to any gate table.** CI never installs hooks, so it would be red by
  construction there. It stays a local command.

## If X then Y

- If `tests-gardener` goes red for you locally on `test_the_map_is_still_true_of_the_real_repo`,
  it is almost certainly stale `__pycache__` under a renamed directory, not a code defect — that
  test reads the real tree. It was `automation/maintenance/` this time; deleting the untracked
  bytecode fixed it and CI never saw it.
- If CI runs the full lane matrix on this PR, that is expected, not a misclassification:
  `automation/bootstrap_overlay.py` has no lane owner in `automation/ci/classify_changes.py`,
  so the classifier fails closed to every lane.

## Dead ends

- None.

## Needs your attention

- Nothing new was filed this session. Standing: 29 pending `message-queue/needs-human/decisions/`
  items, unchanged by this work. Top by `Cost if wrong` (the only `recurring-loss` among them):
  [job-search-us-only-default-asymmetry](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md)
  — the search gate and the draft gate default `us_only` in opposite directions, so a search
  profile that omits the key searches worldwide and the draft gate then refuses those rows.
  **Why this matters:** the waste repeats on every run, not once. **If you do nothing:** the
  default path holds (nothing changes), both shipped profiles already set the key explicitly, and
  only a hand-written profile that omits it keeps paying.

# Verification — 2026-08-20-cleanup-script-rechecks-nothing-at-run-time

Only commands actually run, with their real output.

## The whole workspace suite, including the new run-time-re-check cases

```
$ .venv/bin/python -m unittest discover -s automation/workspace/tests -t .
Ran 155 tests in 133.977s

OK
$ echo $?
0
```

## The task's own definition-of-done case: dirty AND locked after the plan

`PostPlanMutationTests` in `automation/workspace/tests/test_cleanup.py` writes a
plan, then adds an untracked file and locks the worktree with the reason a live
Claude Code session uses, then runs the emitted script.

```
$ .venv/bin/python -m unittest \
    automation.workspace.tests.test_cleanup.PostPlanMutationTests -v
test_a_worktree_dirtied_after_the_plan_is_not_moved ... ok
test_a_worktree_locked_after_the_plan_is_not_moved ... ok
test_a_worktree_whose_status_breaks_after_the_plan_is_not_moved ... ok
test_an_untouched_worktree_in_the_same_run_still_moves ... ok

Ran 4 tests in 5.0s

OK
```

## The same four cases against the PREVIOUS planner (they must fail)

A copy of the tree with `automation/workspace/cleanup.py` reverted to
`origin/main`, run with the identical tests:

```
$ .venv/bin/python -m unittest discover -s automation/workspace/tests -t .
Ran 155 tests in 124.928s

FAILED (failures=25, errors=14)
```

with, among them:

```
FAIL: test_a_worktree_locked_after_the_plan_is_not_moved
FAIL: test_a_worktree_dirtied_after_the_plan_is_not_moved
FAIL: test_a_worktree_whose_status_breaks_after_the_plan_is_not_moved
FAIL: test_an_untouched_worktree_in_the_same_run_still_moves
```

## The original reproduction, re-run against the fix

The adversarial repro that moved a locked, dirty worktree and wedged its branch:

```
$ sh D4-stale-plan-moves-live-worktree.sh <tmpdir>
  RETIRE  <tmpdir>/wt
           it is no longer the worktree this plan measured — it is dirty,
           locked, unreadable or gone. NOT moved
1 item(s) refused; the items above them still ran.
worktree dir now: <tmpdir>/wt
registration:
worktree <tmpdir>/wt
HEAD 5cb5118fbfe8250ad0f75d7cf6f8f6c91f0486e4
branch refs/heads/wtb
```

The directory is intact, its uncommitted file is intact, the registration still
points at a directory that exists (not wedged), and the script exits 1.

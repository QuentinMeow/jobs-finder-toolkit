# Handover — cleanup-evidence-not-refusal

- **Date**: 2026-08-21
- **Task(s)**: 2026-08-20-cleanup-script-rechecks-nothing-at-run-time (now
  `3_in-review`)

## What happened

- Nothing is on fire, nothing is half-done, and nothing was pushed. Three
  commits sit on `fix/i3-cleanup-evidence`; the branch has no PR yet.
- `automation/workspace/cleanup.py` was destroying work in two ways and
  refusing to clean up the exact things the owner cleans by hand. Both are
  fixed, with the reproductions re-run against the fix.
- The two destructive ones: `--execute` ran `git worktree prune` on a
  registration whose directory was gone WITHOUT first sweeping that
  registration's own reflog, so a detached-HEAD commit that lived only there
  was destroyed — and the owner doing the same thing by hand does NOT lose it,
  which is what makes it the tool's fault. And two branch names that slug to
  the same string (`feat/a`, `feat-a`) shared one backup ref, so the second
  write silently replaced the first while both rows reported
  `backup_written: true` and the script printed "Nothing was lost".
- The over-keeping: a detached HEAD was an unconditional keep, and every
  Claude Code harness worktree is detached by construction, so that rule fired
  on 100% of them forever and no flag could waive it. And on this repository's
  own merge shape — squash-merge, remote head branch deleted — two independent
  rules became jointly unsatisfiable, so a merged branch was unretirable
  permanently while the tool exited 0.
- The suite went from 114 tests to 164. 39 of the new ones fail against the
  previous planner, measured.

## Where things stand

- `fix/i3-cleanup-evidence`, three commits, not pushed, no PR. All 23 gates in
  the `policy,maintenance,shared,publish` lanes are green.
- The backlog task this closes is in `3_in-review` with real verification
  output.

## Decisions made for you

- **`git branch -d`'s verdict no longer has the last word when this tool's own
  containment proof contradicts it.** `-d` judges a branch against its upstream
  or HEAD — never the base the planner tested — and after a squash-merge whose
  head branch the remote deleted, it can never be satisfied again. Where the
  fetched base provably contains the branch's whole content, the deletion is
  emitted as `git update-ref -d <ref> <tip>`, a compare-and-swap git refuses if
  the branch moved. No `-D`, no `--force`, no unset upstream, no deleted
  tracking ref, and the `-d` verdict is quoted in the plan and the script.
  Undoing it is reverting one function (`deletion_method`).
- **The "every commit is on a remote" rule is waived when, and only when, the
  fetched base contains the branch's content.** Same shape, same reason: the
  proxy became permanently unsatisfiable while the thing it stands for stayed
  true. Printed as a note on every row it applies to, never silent.
- **The planner now runs its OWN containment probe** rather than trusting the
  dashboard's `merged`, because a `merge-tree` CONFLICT (exit 1) prints the base
  tree for binary files and submodules and so reads as "contained" there. Cost
  of undoing: the planner would inherit that bug again.
- **`git worktree prune` is now all-or-nothing.** It cannot be aimed at one
  registration, so one entry's fail-closed keep now holds back the whole run's
  pruning instead of being overruled by a neighbour.
- **Remote branches are listed, not deleted** — see below.

## If X then Y

- If a later session wants the planner to plan REMOTE deletions, the blocker is
  the filed decision, not missing code. The evidence is already computed; only
  the emitter is absent, deliberately.
- If `tests-workspace` gets slow, it is the fixture count, not any one test:
  164 real git repositories at ~133s total.
- If the `merge-tree` conflict bug bites the DASHBOARD, that is the filed
  backlog task, not a regression here — the planner is already immune.
- `fix/i2-status-truth` was editing `status.py` and `resolve_base` in the same
  file at the same time. `resolve_base` was deliberately left untouched here; a
  conflict there is expected and is that branch's shape, not damage.

## Dead ends

- Tried reproducing the backup-ref collision with `merge --no-ff`: useless,
  because that makes both tips ancestors of `main`, so `main` keeps them alive
  whatever the backup refs do and the collision is invisible. Needs a
  cherry-pick.
- Then tried a plain cherry-pick: with the fixture's pinned author and committer
  dates that rebuilds a byte-identical commit — the same sha — so nothing is at
  risk either. `main` has to move first. Both traps are now asserted in the
  fixture so the next person hits an error, not a green test.
- Tried `git remote set-head` to build the `origin/HEAD` case: it writes a
  SYMREF, and separately `git fetch --prune` deletes a plain ref at that path
  and replaces it with one. The plain shape only survives a stale run.

## Needs your attention

- [Should the cleanup planner delete merged remote branches?](../../../message-queue/needs-human/decisions/plan-remote-branch-retirement.md)
  — **Why this matters**: seventeen merged branches sit on the remote and were
  invisible to the planner until today; the question is whether it should go
  further and write a script that deletes them. **If you do nothing**: it keeps
  listing them and deleting nothing, which is the default path and is safe
  indefinitely — you delete them on GitHub yourself, or they stay.
- [A `merge-tree` CONFLICT reads as `merged` in the dashboard](../../../tasks/0_backlog/2026-08-21-merge-tree-conflict-reads-as-merged-in-the-dashboard/task.md)
  — **Why this matters**: `status.py` prints `merged` for a branch whose content
  is nowhere in main, whenever the conflict is in a binary file or a submodule,
  and this repo tracks 22 files with NUL bytes. **If you do nothing**: the
  cleanup planner is already immune (it re-checks itself), but the dashboard
  keeps telling you a branch is finished when it is not.

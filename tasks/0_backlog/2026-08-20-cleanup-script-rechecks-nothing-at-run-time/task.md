# The cleanup script re-checks nothing between planning and running

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: session 2026-08-20, closing the two `automation/workspace/cleanup.py`
  audit findings (branch `fix/cleanup-worktree-gaps`)

## Goal

The emitted `local/workspace/cleanup-<run>.sh` moves a worktree with an
unconditional `mv`. Every precondition that authorised that move — clean tree,
containment in the fetched base, unlocked, nothing living only in its reflog —
was measured when the PLAN was written, and nothing re-measures it when the
owner actually runs the script. Decide whether each emitted move should carry a
run-time re-check that aborts instead, and implement it if so.

## Context

`automation/workspace/cleanup.py` is a planner with no executor: it classifies,
writes `local/workspace/cleanup-<run>.json`, and emits a shell script the owner
reads and runs. The gap between those two moments is unbounded — a plan written
on Monday can be run on Friday.

For a worktree, the emitted lines are:

    git update-ref <backup ref> <oid> -m 'pre-delete backup'   # if anything is at risk
    git rev-parse --verify --quiet '<backup ref>^{commit}' >/dev/null || { … exit 1; }
    mv <worktree> <trash>/<name>
    git worktree prune

Only the backup ref is verified at run time. The `mv` itself asks nothing. So a
worktree that was clean and unlocked at plan time, and has since gained
untracked files or been re-locked by a live session, is moved anyway. Nothing is
DELETED — the directory lands in `local/workspace/trash-<run>/` intact, which is
why this is P2 and not P0 — but a process working in that directory loses its
cwd mid-run, and `git worktree prune` then drops a registration that was live
again.

`--include-harness-worktrees` (added in the same session) widens the exposure
rather than creating it: `.claude/worktrees/*` are the directories most likely
to change between plan and run, because the Claude Code harness creates and
locks them on its own schedule. The live-session guard today is that lock —
observed on the real repository as
`locked claude agent agent-<id> (pid <n> start <when>)` — and `KEEP_LOCKED`
holds any worktree carrying one. That guard is real, but it is only read once.

Design options worth weighing:

1. emit a per-move re-check (`git -C <wt> status --porcelain` empty, and the
   worktree not locked) that `exit 1`s before the `mv`. Cheap, but the script
   stops mid-plan, leaving a partially applied run — the outcome
   `docs/handbook/post-merge-cutover.md`'s "no half-applied plan" reasoning
   already argues against;
2. emit the re-check as a `continue`-style skip per worktree rather than an
   abort, so the rest of the plan still applies;
3. stamp the script with an expiry (`run_id` age) and refuse outright above some
   staleness, pushing the owner to re-plan;
4. do nothing and document the window in the script header.

Whatever is chosen must not turn the script into something that runs
`git worktree remove`, `rm`, or `git branch -D`
(`docs/handbook/post-merge-cutover.md`, "nothing here deletes owner data").

## Definition of done

- a decision is recorded (`memory/decisions/`, or a
  `message-queue/needs-human/decisions/` item with a default path if it needs
  the owner);
- if a re-check ships, `automation/workspace/tests/test_cleanup.py` gains a case
  that dirties or locks a worktree AFTER the plan is written and asserts the
  emitted script does not move it;
- `.venv/bin/python -m unittest discover automation/workspace/tests` exits 0.

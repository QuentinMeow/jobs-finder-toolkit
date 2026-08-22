# Worklog — 2026-08-20-cleanup-script-rechecks-nothing-at-run-time

## 2026-08-21 — session 1 (agent, branch `fix/i3-cleanup-evidence`)

- Confirmed the claim empirically, and it is worse than filed: the moved
  worktree's registration survived (prune declines a locked entry), leaving the
  branch permanently wedged while the script reported success and exited 0.
- Took option 2 (skip + record a refusal, rest of the plan still runs). Added
  `cleanup_worktree_ready` to the emitted script — existence, not-the-main-tree,
  not-locked, and a `git status` that both runs and comes back empty.
- The same session gave the compare-and-swap branch deletion its own run-time
  checks (tip unchanged, no worktree holding it), so both destructive verbs now
  re-measure what `git branch -d` always re-measured for itself.
- Next: review. Nothing outstanding.

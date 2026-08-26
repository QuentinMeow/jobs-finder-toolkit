# Handover — compact-git-ws-status

- **Date**: 2026-08-26
- **Task(s)**: 2026-08-20-workspace-git-status-command

## What happened

- Nothing is broken; the one-line `git ws` repair is tested and ready for its
  public PR.
- The previous cleanup really left zero local work branches, but the normal
  dashboard mixed two cached remote-only refs into a large table and made that
  result look false.
- Normal output is now one line covering checkout sync, dirty worktrees, and
  local work branches. The complete inventory remains available with `-v`.

## Where things stand

- The implementation is on `codex/compact-git-ws-status`; all 206 workspace
  tests pass, and merge/cleanup will follow the public PR checks.

## Decisions made for you

- Omitted cached remote-only refs from normal output because they are not local
  branches and do not answer whether local cleanup is complete; `-v` and JSON
  retain the data, so undoing this choice is a renderer-only change.
- Kept stale remote knowledge in the one-line output only when it needs action;
  fresh cache ages and explanatory legends remain in the full view.

## If X then Y

- If another checkout still prints the old table after this lands, it has not
  pulled the repair; if it prints the table only with `git ws -v`, that is the
  intended full-inventory mode.

## Dead ends

- Treating cached `origin/codex/*` pointers as evidence that local cleanup was
  incomplete was rejected: they are not local branches, and the local cleanup
  planner is intentionally not authorized to delete GitHub branches.

## Needs your attention

- 40 public items pending · top: [retire-copied-private-companies-root](../../../message-queue/needs-human/decisions/retire-copied-private-companies-root.md) — Why this matters: it is the highest-cost pending choice because it governs owner data; If you do nothing: the verified recovery copy remains and nothing is deleted.

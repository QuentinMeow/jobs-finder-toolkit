# Handover — GitHub refresh and local cleanup

- **Date**: 2026-08-25
- **Task(s)**: `2026-08-25-refresh-main-and-clean-agent-branches`

## What happened

- Nothing is blocked or half-done locally: the cleanup and workflow change are ready for GitHub.
- The one safe, already-merged local agent branch was deleted. No agent worktrees or private-repo
  agent branches needed cleanup.
- The GitHub workflow now requires a fresh-main attempt and a conservative local `codex/` and
  `claude/` branch/worktree sweep before and after GitHub operations.

## Where things stand

- In review on `codex/github-refresh-and-cleanup`; all five canaries and all 32 selected pre-PR
  gates passed. Full evidence is in the [task verification](../../../tasks/3_in-review/2026-08-25-refresh-main-and-clean-agent-branches/verification.md).

## Decisions made for you

- Cleanup is local-only and evidence-based: open-PR refs, unique work, active worktrees, locks, and
  uncertain cases are kept. Worktree retirement stays recoverable through the cleanup planner.
- A dirty or diverged main checkout is reported and preserved instead of being overwritten.
- Remote branches are not deleted because the request covered local branches and worktrees.

## If X then Y

- If a later sweep cannot prove a prefixed branch useless, keep it and report why.
- If main cannot fast-forward, resolve only task-owned conflicts; preserve unrelated edits and
  escalate uncertainty.

## Dead ends

- The generic system skill validator rejects this repository's supported `visibility:` key. The
  repository's own instruction, manifest, canary, and full gate checks were used instead.

## Needs your attention

- Nothing new from this task. Existing unrelated items in the [public decision queue](../../../message-queue/needs-human/decisions/) remain unchanged.

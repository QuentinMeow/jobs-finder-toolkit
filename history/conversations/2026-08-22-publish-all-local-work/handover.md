# Handover — publish-all-local-work

- **Date**: 2026-08-22
- **Task(s)**: none

## What happened

- Nothing discovered was discarded or left without a review path: seven public workstreams and two private-overlay workstreams have focused PRs; none was merged.
- Five unmerged public remote branches were recovered into PRs, the public root's repository-selection edit was committed on its own branch, two detached historical handover commits were recovered by their net content, and both private dirty-file groups were separated and committed.
- The original public root still has the same `AGENTS.md` working-copy edit now carried by `codex/git-repository-selection-preflight`; it was deliberately left untouched until that PR is merged.

## Where things stand

- Public PR branches: `fix/i1-merge-cutover`, `fix/i2-status-truth`, `fix/i3-cleanup-evidence`, `fix/i4-gate-honesty`, `fix/workspace-lifecycle-r2`, `codex/git-repository-selection-preflight`, and this recovery branch.
- Two private-overlay PRs carry the coding-interview style repair and the separate longest-palindrome practice artifact. The private repository has no configured CI checks; both passed their local hooks and targeted verification.
- Merged historical branches were not republished. The detached commits remain reachable through their existing snapshot ref; no branch, worktree, remote ref, or owner artifact was deleted.

## Decisions made for you

- Each independent diff received its own PR because all nine workstreams can be reviewed and reverted separately; combining them would make unrelated history, tooling, and private artifacts move together.
- The stale cleanup-dashboard task was removed from `fix/i3-cleanup-evidence` because `fix/i2-status-truth` already contains the fix and regression coverage; restoring it would create duplicate work.
- Public gates ran with system Git 2.50.1 because the shell-selected Git 2.23 cannot execute the repository's `git init -b` fixtures; changing the shell's global Git configuration was outside this task.

## If X then Y

- If `fix/i2-status-truth` merges before `fix/i3-cleanup-evidence`, rebase the latter and resolve their expected overlap in workspace cleanup code before merging it.
- If the repository-selection PR merges, the original root's identical working-copy edit can be cleared by the owner after confirming it matches `main`; until then, leave it as the recovery source.
- If a public PR turns red after this handover, use its GitHub job log; every public branch was green locally before PR creation.

## Dead ends

- The first public gate runs selected Git 2.23 and failed only where fixtures use `git init -b`; rerunning with system Git 2.50.1 removed those environment failures.
- Two full gate runs in parallel pushed a time-sensitive lifecycle fixture beyond its ten-minute tolerance; the affected branch passed when rerun serially, so the remaining suites were serialized.

## Needs your attention

- [Should the cleanup planner delete merged remote branches?](../../../message-queue/needs-human/decisions/plan-remote-branch-retirement.md) — **Why this matters**: the cleanup PR now lists merged remote branches, but remote deletion would expand its destructive reach. **If you do nothing**: it keeps listing them and deleting none, which is the safe default.
- Existing queues remain open and unchanged; the standing count belongs in the final owner report after the last queue sweep.

# Handover — merge-conflict-cleanup

- **Date**: 2026-08-27
- **Task(s)**: 2026-08-20-workday-detail-429-recovery; 2026-08-25-refresh-main-and-clean-agent-branches; 2026-08-26-issue-263-qualitative-cover-letter; 2026-08-26-issues-267-274-occupation-evidence; no separate task for the merge-driver repair

## What happened

- Nothing is blocked or half-finished. PRs #376, #374, #372, and #373 are merged; issues #267, #274, #235, and #263 are closed; public `main` is clean and synchronized at `3f3d123c`.
- PR #376 repaired the native-stack driver after live stack #375 became stranded behind an already-merged historical member. The explicit complete-prefix resume path independently confirms every merged predecessor, freshly revalidates the open suffix, and refuses holes or stale topology before a merge request. Its behavioral evidence is recorded in [the GitHub-workflow eval result](../../../evals/results/github-workflow-55564ef5772a-20260827-stack-resume.md).
- Every feature branch absorbed the latest `main` through normal merge commits. The only conflicts were in the append-only public review ledger; each resolution preserved both parent histories, passed independent review, and left feature bytes unchanged.
- After every merge was independently confirmed, the cleanup workflow moved six obsolete worktrees into recoverable trash batch `20260828T003655Z` and deleted five contained local branches with the safe branch-deletion path. Three unrelated unmerged branch worktrees and one detached validation probe at `88b22d2b` were retained, and no remote branch was deleted.
- Every retired checked-out tree was already contained in `main`, and all five retired branch tips were contained, but the issue-263 reflog held two non-tip commits. Cleanup preserved `aad1e320bf8b` and `e476da499dbd` under `refs/agent-trash/20260828T003655Z-worktrees/issue-263/` before retiring that worktree.

## Where things stand

- The four existing tasks named above are merged and verified in `tasks/4_done/`. This records-only follow-up is ready for review on `codex/merge-session-handover`; it changes no runtime behavior.
- The four merged PR head branches still exist on GitHub because the standing cleanup policy is local-only. Their corresponding local branches and worktrees no longer exist.

## Decisions made for you

- Used normal merge commits to refresh reviewed branches instead of rebasing or force-pushing them; undoing that choice would rewrite reviewed history and orphan review evidence.
- Limited the stack-resume repair to an explicitly named, complete native-stack prefix; accepting an omitted or inferred predecessor would weaken the driver's fail-closed boundary.
- Kept cleanup recoverable and local-only. The trash batch remains available until a later local purge, and remote deletion remains governed by its existing owner decision.

## If X then Y

- If a future native stack retains merged historical positions, pass the complete prefix with `--atomic`; never submit the higher position alone or retarget it by hand.
- If any retired worktree is needed again, recover its files from trash batch `20260828T003655Z`. Recover the issue-263 reflog-only history from `refs/agent-trash/20260828T003655Z-worktrees/issue-263/aad1e320bf8b` and `refs/agent-trash/20260828T003655Z-worktrees/issue-263/e476da499dbd`; the trash directory alone does not preserve those commits after reflog pruning.

## Dead ends

- The original stack command stopped at the already-merged position, while the higher PR alone failed the bottom-position check. Treating all merged PRs as skippable was rejected because it would bypass ordinary-PR and incomplete-prefix safeguards.
- Two reviewed branch heads became stale while lower PRs merged. Publishing them unchanged was rejected; each absorbed the new `main`, reconciled the ledger, and reran exact-head checks.

## Needs your attention

- Nothing new from this session. The existing public decision queue is unchanged.
- 41 pending · top: [retire-copied-private-companies-root](../../../message-queue/needs-human/decisions/retire-copied-private-companies-root.md) — doing nothing keeps the recovery copy and deletes nothing.

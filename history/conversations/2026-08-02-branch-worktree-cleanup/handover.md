# Handover — branch-worktree-cleanup

- **Date**: 2026-08-02
- **Task(s)**: none

## What happened

- Nothing is in flight or broken; both repositories now have current local `main` branches and only `origin/main` as a remote branch.
- Merged local feature branches and four redundant public worktrees were removed; two of those worktrees held only generated fake-example document outputs from a completed gate run.
- One unmerged public handover branch and one Codex-managed worktree remain because each still carries useful, unmerged or resumable work.

## Where things stand

- The public repository has `main` plus one useful unmerged handover branch, and two worktrees: the main checkout and one worktree attached to an idle, resumable task.
- The private repository has only `main`; all private feature branches were already merged and were removed. Existing untracked owner files are unchanged.
- A byte-identical recovery copy of one formerly untracked private configuration file remains in temporary storage after its tracked copy arrived through the private `main` fast-forward.

## Decisions made for you

- Merged branches were deleted only when their complete tips were ancestors of fetched `origin/main`; restoring one costs finding the merge commit, while no unique content was lost.
- The unmerged handover branch was kept only until its required session record could be rebuilt on current `main`; keeping the record costs one small records change, while deleting the sole ref would discard useful history.
- The remaining Codex worktree was kept because the app reports its task as idle and resumable; deleting it could disrupt that task.
- The archived JD-digest ref was kept under its pending owner decision because it is the sole copy of tested external-response fixtures.

## If X then Y

- If the resumable task is archived or no longer needed, remove its clean detached worktree after confirming it has no unique files; the completed handover content is being made durable on `main` separately.
- After the handover record lands on `main`, delete the obsolete local branch after fetching and rechecking the resulting tree.

## Dead ends

- Force-removing a dirty temporary worktree was rejected because ignored files were initially unclassified; inspecting them showed only test caches and logs, so the four generated example outputs were restored and the clean worktree was removed without force.
- The first private fast-forward stopped before overwriting an untracked file; its blob was byte-identical to the incoming tracked file, so a recovery copy was preserved and the fast-forward completed.

## Needs your attention

- Nothing from this cleanup. Existing decisions remain open.
- 29 pending · top: [job-search-us-only-default-asymmetry](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md) — inconsistent search and draft defaults can repeatedly admit roles that later cannot be drafted.

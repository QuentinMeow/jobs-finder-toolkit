# Handover — multi-worktree Git safety

- **Date**: 2026-08-03
- **Task(s)**: `2026-08-03-multi-worktree-git-safety`

## What happened

- Nothing is on fire, but the owner's primary checkout still displays the
  artificial staged state created by the old cleanup helper; this task did not
  mutate that checkout to repair it.
- Cleanup, hook installation, exclusions, push scanning, and recovery guidance
  now have worktree-safe fixes split across three reviewer-sized PRs. PR #302's
  conflict with newly merged PR #300 is resolved without rewriting history.

## Where things stand

- cursor-undercover-recipes PR #45 and jobs-finder-toolkit PR #302 are open;
  workflow-guidance PR #305 is stacked on #302 and includes the resolved bottom
  branch. The task is in review and CI is rerunning on the updated tips.

## Decisions made for you

- Remote refreshes update only remote-tracking refs; local branches are never
  advanced by cleanup. Undoing this would restore the original corruption path.
- Guards inspect immutable outgoing Git objects and resolve the invoking
  worktree at runtime. Undoing this would reopen bypasses from non-HEAD branches.
- The existing artificial primary-checkout state was preserved because repair
  would overwrite index state and requires explicit owner approval.
- Main was merged into the bottom branch and the bottom into its child, rather
  than rebasing either. This preserves reviewed SHAs and costs two explicit
  merge commits plus their review-ledger rows.

## If X then Y

- If `main` advances into conflict again, merge it into PR #302 in its owning
  worktree, then merge the updated bottom into PR #305; do not rebase the native
  stack or use GitHub's Update Branch button.

## Dead ends

- A direct primary-checkout reset was not approved, so no repair was attempted.
- Automatic merge of the separate source-repository PR was refused; the PR was
  left open for explicit review instead.

## Needs your attention

- This task adds no queue item. The 32 pre-existing public needs-human items
  remain listed under `message-queue/needs-human/`; the highest-cost item is
  `job-search-us-only-default-asymmetry` because its default can repeatedly omit
  roles. Silence leaves every existing default path in effect.

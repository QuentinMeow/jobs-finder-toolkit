# Merged branches are swept after their PRs close, but `delete_branch_on_merge` stays off

- **Status**: decided
- **Date**: 2026-08-22
- **Decided by**: owner
- **Supersedes / Superseded-by**: narrows the scope of the retention rule in
  `skills/github-workflow/SKILL.md` (which stands unchanged for merge time)

## Context

The public repository's branches page had accumulated 18 branches,
17 of them belonging to PRs that were merged and closed. Nothing was responsible for
removing them, and that was not an oversight: retention is documented in
`skills/github-workflow/SKILL.md` and `CONTRIBUTING.md`, and ENFORCED in code —
`merge_stack.py` rejects `--delete-branch` at argument parsing.

The reason is real and this repo has the scar. In `#136`, deleting a base branch closed the
PR stacked above it **one second later** (`base_ref_deleted` 21:05:08 → `closed` 21:05:09).

But that policy answers only *"may the merge command delete the head branch at merge time?"*
— correctly, no, because a stack above it may still be live. It never answered what happens
weeks later when no PR anywhere points at the branch. The prose generalised to "forever" and
nothing recorded the boundary, so branches accumulated with no owner.

## Decision

Retire a branch once its work is in `main` and nothing depends on it. `delete_branch_on_merge`
**stays `false`** — the sweep happens after the fact, never at merge time.

Eligibility, all three required:
1. not `main` or otherwise protected;
2. no open PR names it as head **or as base**;
3. its content is provably contained in the fetched `origin/main` — `git merge-tree
   --write-tree origin/main <branch>` yields `origin/main`'s exact tree.

Local deletions use `git branch -d` only. Remote deletions use
`git push origin --force-with-lease=refs/heads/<b>:<sha> :refs/heads/<b>`.

## Alternatives considered

- **Turn on `delete_branch_on_merge`.** Lost: it fires at merge time, the exact moment `#136`
  proves lethal, and it would not have touched the 17 branches that prompted this.
- **Have `merge_stack.py` delete the head branch after merging.** Lost: same timing problem,
  and it is the one lifecycle rule this repo mechanically enforces against.
- **Leave them.** Lost: the owner asked for the cleanup after the list reached 18 and
  "which of these is live work?" could only be answered by opening each one.
- **Plain `git push origin --delete`.** Lost: measured to succeed unconditionally and to lose
  commits raced in after planning. The lease refuses a stale ref.
- **`--atomic` across the batch.** Lost: measured — one stale lease aborts every deletion.

## Consequences

- The sweep is a **one-off performed under explicit owner instruction**, not automation.
  `automation/workspace/cleanup.py` still LISTS remote branches and emits nothing; it gained
  no `push --delete` code path. Automating it needs a new decision.
- Nothing became unreachable: every deleted branch was an ancestor of `origin/main`, so its
  commits survive in a fresh clone.

**Revisit if** the open `public-history-privacy-rewrite` decision is ever executed. It would
rebuild `origin/main`, and every "contained in `origin/main`" verdict taken beforehand becomes
false retroactively — a branch deleted as redundant could hold the only copy of a commit the
rewrite dropped. That is the argument against ever putting this sweep on a schedule.

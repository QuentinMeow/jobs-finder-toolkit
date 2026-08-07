# Handover — reconcile-local-work-after-private-refactor

- **Date**: 2026-08-07
- **Task(s)**: [2026-08-06-private-overlay-personal-taxonomy](../../../tasks/4_done/2026-08-06-private-overlay-personal-taxonomy/task.md)

## What happened

- Nothing substantive remains in flight: the person-first public/private refactor and the preserved private mailbox/calendar reconciliation are merged.
- Both mounted repositories were updated to the new layout, the ignored local config was cut over, and the task-owned temporary worktrees were removed.
- Ignored files that Git could not rename were copied non-overwriting into the new company-interview tree and verified byte-equivalent. The retired copies remain because only the owner may delete them.

## Where things stand

- Private PR #94 is merged. This branch contains only the public task closure, handover, and owner-retirement decision needed to finish the session record.
- The mounted public and private checkouts have no tracked or untracked changes beyond this intentional public closeout branch.

## Decisions made for you

- The old dirty patch was checkpointed before rebasing, preserving its recorded hash and giving the rename reconciliation a recoverable commit. Undoing this is low cost because the checkpoint commit remains in Git history.
- Calendar conflicts were resolved only after proving the refactor changed those files solely by one relative-path rewrite. Reverting the reconciliation would be a one-commit change.
- Ignored legacy files were copied with `--ignore-existing` and checksum-verified; no source was deleted. The extra disk use remains until the owner decides whether to retire the old root.
- Local `config.yaml` now names the person-first roots. Reverting it is easy but would make current tracker commands resolve retired paths.

## If X then Y

- If the owner approves retirement, manually remove only `private/companies/` after an optional spot-check; do not touch the active `private/me/interviews/companies/` tree.
- If a tracker command resolves an old path, inspect the ignored local config first; all current accessors were verified against existing new-layout destinations.

## Dead ends

- The first rebase could not auto-merge the generated calendar because content updates and relative-link rewrites touched the same lines. A base-to-main comparison proved the layout delta was path-only, which made the mechanical resolution safe.

## Needs your attention

- [Retire the copied private company root](../../../message-queue/needs-human/decisions/retire-copied-private-companies-root.md) — Why this matters: the inactive root duplicates about 46 MiB and can confuse manual browsing. If you do nothing: it remains a safe ignored recovery copy and tooling continues using the new tree.
- [Behavioral fabrication category scope](../../../message-queue/needs-human/decisions/behavioral-fabrication-category-scope.md) — Why this matters: it controls whether agents may choose invented claims within broad categories. If you do nothing: authorization stays limited to exact human-named claims.
- The private handover from the mailbox/calendar refresh retains its unresolved role-link decisions. If you do nothing: their conservative unlinked defaults continue and no application history is guessed.

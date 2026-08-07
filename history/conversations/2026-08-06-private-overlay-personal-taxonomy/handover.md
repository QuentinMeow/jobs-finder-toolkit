# Handover — private-overlay-personal-taxonomy

- **Date**: 2026-08-06
- **Task(s)**: 2026-08-06-private-overlay-personal-taxonomy

## What happened

- Nothing is on fire; two cross-repository PRs are in review and the mounted private checkout's unrelated work remains byte-for-byte untouched.
- Personal artifacts now follow `me/{career,applications,interviews}`; market, store, skill, eval, and process systems remain top-level.
- The public dependency passed 29/29 config-less gates after the first run found and prompted five missed test-path corrections.

## Where things stand

- Public toolkit PR #321 is green and must merge before dependent private-overlay PR #93.
- The ignored real config and dirty mounted private checkout still use the old tree; cutover waits until both PRs merge and the unrelated work is preserved.

## Decisions made for you

- Company interview prep lives under `me/interviews/companies/`, but the cross-workflow identity registry lives under `market/`; undoing this means reverting both PRs.
- Career source and communication files live under `me/career/`, leaving only directories directly below `me/`.
- The re-created legacy `data/` root stays untouched because it contains unique newer state; a separate task must reconcile it before any owner-only retirement.
- No compatibility symlink was added because two valid homes would permit split writes.

## If X then Y

- If the private PR is ready before the public PR, wait: the accessor/default contract must land first.
- If the mounted checkout's unrelated edits are still dirty at cutover, preserve them before switching branches or changing the ignored config.

## Dead ends

- The first config-less gate run failed because five tests still named retired example paths; those paths were corrected and the full rerun passed.
- The copied private Git hooks could not locate the toolkit from a linked worktree; preserved copies were replaced with their contractually intended toolkit symlinks, after which every guarded commit and push passed.

## Needs your attention

- Review public PR #321 before private-overlay PR #93. Why this matters: merge order controls whether validators understand the new tree. If you do nothing: both branches remain inert and no owner data moves.
- The pre-existing needs-human queue remains unchanged (34 items); its highest-consequence items still use their recorded safe defaults while pending.

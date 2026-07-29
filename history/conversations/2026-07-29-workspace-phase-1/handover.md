# Handover — workspace-phase-1

- **Date**: 2026-07-29
- **Task(s)**: `tasks/4_done/2026-07-28-workspace-phase-1-orphans`

## What happened

Phase 1 of the workspace restructure. Both orphaned items are refiled inside the overlay and the
two stray trees are gone. `tmp/` was classified rather than emptied — nothing was deleted.

Two things the plan got wrong, both caught only by reading the files it named:

- It said to file the orphaned task into `0_backlog`. The file said `Status: done` and carried a
  resolution with a confirmed root cause and a shipped fix. Every artifact that resolution
  claimed was re-checked against the current tree — all six present, the vendored copy matching
  its canonical module line for line — so it went to the overlay's `4_done` with a
  `verification.md`. One definition-of-done bullet had never been run; it is recorded as not run
  rather than quietly ticked.
- It said this phase's public half was empty. Sweeping `tmp/` found three durable records — two
  `evals/results/` rows and the task above — citing snapshot files under `tmp/` that no longer
  exist. A record that cites scratch is evidence with an expiry date and no expiry signal, so
  that is now a rule in the scratch section of `handbook/file-organization.md`.

Most of `tmp/` turned out to be yours: one folder holds complete application folders with real
employers and your name in the filenames, another holds interview screenshots. The never-delete
guardrail puts all of that out of an agent's reach, so the sweep's deliverable is a
classification for you to act on, not a cleanup.

## Where things stand

- Two stacked PRs open against `main`: the handbook rule at the bottom, the phase record on top.
  The bottom one stands on its own — it is worth having whether or not phase 1 ever ran.
- The overlay carries the two refiles in one commit.
- `tasks/0_backlog/` is empty of started work; phases 2 and 5–8 remain filed and unstarted.
- Depth is in the task folder's `verification.md` — the real command output, and the table of
  the three dead citations.

## Needs your attention

- The `tmp/` classification is a review item in the overlay's queue: what is safe to delete, what
  is regenerable, and what only you may touch. Roughly a gigabyte is recoverable if you clear the
  cached search snapshots, but three folders are application and interview material that I will
  not touch under any instruction.
- [Config discovery fallback](../../../message-queue/needs-human/decisions/config-discovery-example-fallback.md)
  — implemented on the default path (raise only when an overlay is mounted). Confirm, or pick the
  stricter option and two docs get rewritten to match.
- [Private-scope reconciler](../../../message-queue/needs-human/decisions/private-scope-reconciler.md)
  — none exists, so the overlay hook reports the skip. Your overlay's process layer has findings,
  so enabling it today blocks your next overlay commit until they clear.
- [Logs as store projections](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  — pre-existing, unrelated, still open.
- [Workspace layout review](../../../message-queue/needs-human/reviews/workspace-restructure-plan.md)
  — answered and folded two sessions ago; safe to delete once you have confirmed nothing was
  mis-folded.
- Your overlay has an unstaged deletion of a decision file from an earlier session, untouched by
  this work. Commit it or restore it before the next overlay change, so it does not ride along in
  someone else's commit.
- Phase 2 renames `tmp/` → `local/`. That tree still contains your application data, so it is a
  move, never a clean.

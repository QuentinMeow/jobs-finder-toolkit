# Handover — workspace-phase-5-and-the-link-checker

- **Date**: 2026-07-30
- **Task(s)**: `2026-07-29-verify-links-misses-markdown-and-nonstrict-roots`,
  `2026-07-28-slim-company-research-skill`, `2026-07-28-workspace-phase-5-lifetime-taxonomy`

## What happened

Three of the six planned pieces landed. The link checker was rebuilt and, for the first
time, wired into CI and pre-commit — it previously ran nowhere but its own unit tests.
The company-research skill was slimmed from 595 to 469 lines, clearing the budget that
blocked phase 8. And workspace phase 5 executed: **747 tracked files relocated across
the private overlay**, into `me/` · `companies/` · `market/` · `store/`, with
`applications/<status>/<slug>/` untouched and the tracked total unchanged at 3,186.

Reconnaissance changed the phase before it started. Three findings would each have
produced a migration that looked finished and was not: the link checker could never have
verified this phase's own repair step (it never read a single file inside the overlay);
33 story references would have hard-failed the answer bank, and the obvious repair was a
content edit the owner's own ruling forbids; and splitting the card/log config accessors
the obvious way would have pointed benchmark runs at the real tailoring card and the real
skip-log. All three are handled, and the reasoning is in the task folders.

Phases 6, 7 and 8 are **not started**. Their preconditions are now met.

## Where things stand

- **Public repo**: a four-PR stack, all CI-green, none merged. Merge bottom-up.
- **Private repo**: one PR, 32 commits. **Merge the public phase-5 PR first** — it is
  what teaches the toolkit where the moved files went.
- **`config.yaml` is already updated on this machine** (7 path keys → 16). It is
  git-ignored, so no PR carries it; the block is in the session scratchpad. A fresh
  clone needs it pasted, or every accessor resolves to its old location and fails loudly.
- **`pre-phase-5-snapshot`** tags the private repo's pre-migration state. It earned its
  keep once already.

## Needs your attention

- **[Should phase 5 untrack the 48 session handovers?](../../../message-queue/needs-human/decisions/history-untracked-in-phase-5.md)**
  The plan's move table sends `history/` to an ignored directory in both repos — 48
  tracked files leaving git entirely, which is the only row that subtracts from a
  history rather than relocating within one. Dropped from phase 5 and filed; recommendation
  is to decide it separately from the migration, with a third option that keeps
  everything tracked.
- **[The story bank keeps its directory name — confirm?](../../../message-queue/needs-human/decisions/story-bank-keeps-its-leaf-name.md)**
  Already implemented, filed for the record. Renaming it to the design's spelling would
  have forced a 33-line edit inside files your interview ruling said not to alter.
- **[Where does the coding-interview screenshot inbox live?](../../../message-queue/needs-human/decisions/coding-interview-todo-inbox-home.md)**
  Left exactly where it is, on purpose — changing a folder you drag files into
  mid-interview is not something to slip into a 747-file migration.
- **Still open from before, unchanged:**
  [private-scope reconciler](../../../message-queue/needs-human/decisions/private-scope-reconciler.md)
  (you deferred this deliberately — not re-asking) and
  [logs as store projections](../../../message-queue/needs-human/decisions/logs-as-store-projections.md) (parked).
- **Phase 6 should not wait long.** Phase 5 makes deleting an application *look* safe
  while the skip-log is still regenerated from the application folders — so deleting a
  rejected application and re-syncing still re-opens the posting.

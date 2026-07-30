# The old applications-log.yaml is now unread — delete it, or keep it?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-30
- **Source**: [workspace phase 6 — the skip-log becomes authoritative](../../../docs/designs/workspace-restructure/execution-plan.md)
- **Blocking**: nothing
- **Default path**: agents leave the file exactly where it is and never read it. No tool
  writes it any more; `--backfill-log` reads it once and names it in its output.

## Background

Phase 6 replaced the regenerated YAML skip-log with an append-only
`applications-log.jsonl`. Every reader and every writer moved in the same change:
`load_considered`, `handoff._posting_keys`, the recall audit, the funnel metric, and the
store refilter all fold the JSONL now, and `--sync-log` appends to it instead of rewriting
the YAML.

That leaves `applications-log.yaml` sitting in the overlay's `market/logs/` folder,
current as of its last sync, read by nothing. It is a file in your tree, so removing it is
your call, not an agent's — agents never delete owner data under any condition, including
cleanup and migration.

Concretely, the file is a projection of the application folders that the JSONL was seeded
from. Everything in it is in the JSONL. Its only remaining value is as a second copy of
the pre-migration state, and git history in the overlay already holds that.

## Options

### Option A — delete it

`rm private/market/logs/applications-log.yaml` and commit in the overlay. One less file
that looks authoritative and is not; nobody can accidentally hand-edit the wrong log. The
pre-migration state stays recoverable from overlay git history. Costs nothing.

### Option B — keep it as a frozen snapshot

Leave it, or rename it to something ending in `.retired`. Buys a copy of the pre-phase-6
state that does not require a `git show`. Costs a file that reads as live, and
`config.applications_log_path()` keeps resolving to it (the accessor stays, because
`--backfill-log` needs it and because deleting a config key you might re-seed from is
worse than an unused one).

## Recommendation

Option A, but not urgently — verify the JSONL first. Run a search and confirm the skip
count looks right (the fold should hold 369 postings), then delete. Keeping a
stale-but-plausible copy of a safety-critical log is the failure mode phase 6 exists to
remove; git history is the better archive and it is already there.

**Your answer:** ______

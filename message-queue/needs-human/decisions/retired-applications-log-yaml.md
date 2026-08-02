# The old applications-log.yaml is now unread — delete it, or keep it?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-30
- **Source**: [workspace phase 6 — the skip-log becomes authoritative](../../../docs/designs/workspace-restructure/execution-plan.md)
- **Blocks**: nothing
- **Default path**: agents leave the file exactly where it is and never read it. No tool
  writes it any more; `--backfill-log` reads it once and names it in its output. **This
  default is now the weaker option, not the safe one — see the 2026-07-31 update below.**
- **Cost if wrong**: ratify
- **Safe to merge because**: the file is inert: agents never read or write it, so leaving it costs
  nothing and only the owner may delete it.

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

### Update, 2026-07-31 — the precondition is met, which flips which option is the safe one

The recommendation above said "verify the JSONL first" and named the number to check.
**It checks out**, measured directly through `config.applications_jsonl_path()`:

```
events: 369
distinct urls: 367
```

Exactly the 369 the recommendation predicted, and the 367 matches the URL figure in
`docs/roadmap/current-state.md`. Both files are on disk side by side (YAML ~88 KB, JSONL
~114 KB).

**What that changes.** While the JSONL was unverified, "leave the old file in place" was the
conservative default — it kept a fallback. Now that the JSONL is confirmed to hold the full
fold, the old YAML is no longer a fallback; it is a **second file that looks authoritative,
is not, and is drifting further from reality with every append to the JSONL.** The default
path is therefore now the *weaker* option, and it will keep getting weaker on its own.

This is still your file and your call — agents never delete owner data. But the reason to
wait has expired, and the thing that changes if you keep waiting is that the stale copy
becomes more misleading, not less.

**Your answer:** ______

# Worklog — 2026-07-31-incremental-index-rebuild-has-no-build-aside

## 2026-08-02 — session 1 (Claude, branch `fix/22-build-postings-correctness`)

- **The filed scope overstated this**, and `task.md` now carries a dated correction in place.
  The filed evidence claims the failed write leaves `postings.jsonl` gone
  (`after : postings.jsonl exists? False`). It does not. `_regen_index_zone` already excluded
  it (`if stale.name != "postings.jsonl"`), exactly because it is the durable floor. What the
  injected ENOSPC actually destroys is `by-day/` and `triage/`, both of which are re-derived
  from this build's entities and suppressed rows — and the crash leaves the write-ahead
  `postings-build-incomplete.json` marker, so the NEXT build takes a full fold and regenerates
  both. A transient hole `--rebuild` does not have, not lost durable history.
- Fixed anyway, at the smaller size the real scope justifies. `_regen_index_zone` now writes
  first and removes only `before - written`: `_write_index` and `_write_suppressed` report the
  paths they wrote. No `rmtree`, no build-aside, no second `_swap_dir` pair inside `index/`.
  The task's "check a full build-aside against the incremental path's whole point (it exists to
  be cheap)" note is what steered this — write-then-prune costs one extra listing of two
  directories and copies no survivor rows a second time.
- Kept the pruning honest: an emptied bucket still loses its file, and a directory the
  regeneration empties completely is removed, because a fresh-aside `--rebuild` produces no
  such directory and the two paths must not disagree by one empty dir.
- NOT addressed (out of this task's scope, still true): `build_incremental` skips the
  `_verify_schemas` pass `build_rebuild` runs before its swap.
- Shipped as commit `2157948` with three regressions.

# Worklog — 2026-07-31-store-opinions-only-deletes-index-only-survivor-rows

## 2026-07-31 — session 1 (agent)

- Reproduced the destroy on a scratch store: raw + derived removed for one entity,
  `--opinions-only` drops its index row and nothing brings it back.
- Chose to enforce the durable floor at the single writer of
  `index/postings.jsonl` (`_write_postings_index`) rather than thread the survivor
  set into the fourth call site. Threading is what failed here — three paths had it,
  the fourth did not — and a fifth path added later would fail the same way.
- `_regen_index_zone` no longer unlinks `postings.jsonl` before the write, because
  the floor is now read from the live file at write time. Final bytes unchanged (the
  write replaced it wholesale anyway).
- `_patch_index_zone` now hands the writer only the rows it accounts for
  (`all_keys` ∪ `working`) and lets the writer mark and preserve the rest. Side
  effect: a frozen-tombstoned key with no cache entry is now dropped on the fast path
  as it already was on the regen path — an incremental-vs-rebuild divergence closed,
  not opened.
- Took the adjacent zero-entity `--rebuild` crash in the same change: the aside dirs
  are created up front, so a build with nothing to derive commits instead of dying
  mid-swap with the live `derived/` renamed away.
- Next: review. Nothing pending on this task.

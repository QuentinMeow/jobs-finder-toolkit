# Rows a past `--opinions-only` run destroyed may still be in your index's git history

- **Filed**: 2026-07-31
- **Look at**: `git log -p -- <store>/jobs/index/postings.jsonl` in whichever repo
  tracks your store's `index/` zone, comparing the key set before and after any
  commit that followed a `build_postings.py --opinions-only` run.
- **Why you might care**: until this branch, `--opinions-only` deleted every
  `carried_from: index` row — postings whose raw and derived were both absent on that
  machine. Those rows exist nowhere else in the store, and `--rebuild` cannot
  reconstruct them. But `index/postings.jsonl` is committed, so **its git history is
  the one place a destroyed row can still be found**. If you have ever run
  `--opinions-only` on a partial checkout, that history is the only recovery path, and
  it stops being one if the branch is ever squashed or the history rewritten.
- **If you do nothing**: nothing further is lost. The fix on this branch stops any
  future run from destroying a row, and a store that has always had its full raw and
  derived present was never affected — on such a machine the survivor count is 0 and
  the index bytes were identical either way. This item is purely about rows that may
  already be gone.
- **Resolution**:

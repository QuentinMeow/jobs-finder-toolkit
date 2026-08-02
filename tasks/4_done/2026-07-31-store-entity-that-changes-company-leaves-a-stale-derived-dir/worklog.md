# Worklog — 2026-07-31-store-entity-that-changes-company-leaves-a-stale-derived-dir

## 2026-08-02 — session 1 (Claude, branch `fix/22-build-postings-correctness`)

- **The filed scope understated this.** The task calls it tree drift — "the incremental store
  holds a duplicate posting a `--rebuild` does not have" — and notes in passing that
  `_carry_forward` sees the orphan. It does more than see it. `_carry_forward` iterates
  `sorted(rglob("posting.yaml"))` assigning `out[key]`, so the alphabetically LAST partition
  WINS. Rename `Zeta Corp` -> `Alpha Labs`, then lose raw locally (the owner's normal
  multi-laptop state), and the next build reinstates the pre-rename company and title into the
  index. `validate_store` reports `ok=True` throughout and no later full fold cleans it up. That
  is a silent content reversion of a live index row, not a stray directory.
- Fixed in `_write_entity`: it now sweeps the entity's dirs at every other partition
  (`_drop_stale_partitions`) and removes a partition dir the sweep empties. The partition
  snapshot (`_partition_index`) is taken once per build and passed as a REQUIRED keyword, so
  no write path can be added without one.
- Also closed the detection half the task flagged as a watch-out: `_derived_keys` now returns
  `(partition, key)` PAIRS, so the fast path refuses on a fork that predates the fix (the cache
  holds one partition per key, so a key set could never see one). The full fold that follows
  heals it.
- Deletion review, per the task's own "deserves its own review" note: this is the builder's
  first deletion of a derived directory. The zone deleted is exactly
  `<derived>/postings/<partition>/<key>/`; `raw/`, `annotations/` and `state/` (including
  `state/frozen-facts/`) are never touched, and every byte removed re-derives from raw or a
  frozen snapshot. The code refuses structurally as well: the target is resolved and must be a
  direct grandchild of `<derived>/postings` or the build raises `BuildError`. A
  `samefile` guard keeps a case-insensitive filesystem ("UsCo" vs "usco" are ONE directory)
  from deleting the entity just written.
- Shipped as commit `5fce4ba` with four regressions.

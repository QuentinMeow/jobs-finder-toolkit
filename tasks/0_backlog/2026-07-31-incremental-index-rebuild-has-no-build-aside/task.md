# The incremental index rebuild destroys the live index before writing the new one

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: adversarial store audit, finding 4's "aggravating factor" (the same
  audit's `_swap_dir` crash-remnant half is fixed in the store-data-loss PR)
- **Claimed-by**:

## Goal

Make the default (incremental) build path as crash-safe as `--rebuild`: the index
zone survives a failure inside the write, instead of being deleted first and held
only in memory.

## Context

`build_rebuild` writes the whole index into `index.building` and then swaps it in,
so a failure anywhere before the swap leaves the live index untouched. The
incremental path does the opposite. `_regen_index_zone`
(`skills/job-search/scripts/build_postings.py`) `rmtree`s `by-day/` and `triage/`
and unlinks every `*.jsonl` **before** `_write_index` runs, so the only copy of the
index during that window is the in-memory `entities` dict plus `index_survivors`.
Any failure inside the write — ENOSPC is the audit's demonstration — leaves the
index zone empty:

```
before: postings.jsonl rows = 3
write failed: [Errno 28] No space left on device
after : index dir contents = []
after : postings.jsonl exists? False
```

That matters more than a normal lost-cache would, because the committed index is
the store's **durable floor**: rows whose raw blobs were pruned and whose derived is
gone exist nowhere else (`memory/decisions/job-index-durable-floor.md`).
`build_incremental` also skips the `_verify_schemas` pass that `build_rebuild` runs
before its swap, so the incremental path writes with less checking as well as less
safety.

The shape of the fix already exists in the file: write the new index zone into
`index.building` and reuse `_swap_dir`, which now also restores a crash remnant
(`_recover_swap_remnant`). That makes the default path follow a code path the
rebuild path already exercises, rather than inventing a second one.

Note that a full build-aside for the incremental path copies the survivor rows once
more per build; check that against the incremental path's whole point (it exists to
be cheap) before committing to it.

## Definition of done

- `_regen_index_zone` builds aside and swaps; no path deletes the live index zone
  before its replacement is fully written.
- A test injects a failure inside the index write and asserts the pre-existing
  `postings.jsonl` rows — including index-only survivors — are still readable
  afterwards. It must fail against the current code.
- `skills/job-search/scripts/tests/test_build_postings.py` still passes, including
  `IndexPreservationTests` and the incremental-equals-rebuild byte-identity tests.

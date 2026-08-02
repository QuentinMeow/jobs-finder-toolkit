# `--opinions-only` deletes the committed index's index-only survivor rows

- **Priority**: P0 (blocks work)
- **Area**: job-search
- **Source**: adversarial review of the O(new) incremental store build, 2026-07-31 —
  **pre-existing**, introduced by `27021b6` (which added the durable index floor but did
  not thread it into `build_opinions_only`); out of scope for that fix
- **Claimed-by**: agent, 2026-07-31 (branch `wip/33-store-p0-data-loss`; work complete, in review)

## Goal

`build_postings.py --opinions-only` must preserve index rows whose raw and derived are both
gone — the rows that exist nowhere else in the store.

## Context

The job-postings design makes `index/postings.jsonl` a **durable floor**: a row whose entity
has no raw and no derived on this machine, and no tombstone, is carried forward verbatim and
marked `carried` / `carried_from: index`. Both real build paths honour it —
`_regen_index_zone` and `_patch_index_zone` are handed the survivor set.

`build_opinions_only` calls `_write_index(...)` **without** `index_survivors`. Since it
builds `entities_for_index` by walking `derived/postings/*/posting.yaml`, an entity with no
derived contributes no row, and the write drops it:

```
after build:             ['gh-111', 'gh-222']
after raw+derived loss:  ['gh-111', 'gh-222']   (gh-222 index row carried: True)
after --opinions-only:   ['gh-111']             <-- durable index floor destroyed
```

This is the highest-severity item in the batch because the destroyed rows are the only
surviving record of those postings — the design's own "missing derived is as normal as
missing raw" case, which is a real multi-machine scenario for this owner, not a
hypothetical. `--opinions-only` is documented as a cheap re-classification pass, so nothing
warns that it can drop history.

`--opinions-only` also does not write the fold cache. Check whether the fix needs to touch
that too, or whether leaving the cache alone stays sound once survivors are preserved.

## Definition of done

- [ ] `--opinions-only` preserves every `carried_from: index` row verbatim, at its original
      `seq`
- [ ] A test builds a store, removes one entity's raw *and* derived, confirms the row
      survives an incremental build, then runs `--opinions-only` and asserts it still
      survives
- [ ] The `by-day` / `triage` zones are unaffected by the change (`--opinions-only` does not
      write them today)
- [ ] `.venv/bin/python -m unittest discover -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests` passes

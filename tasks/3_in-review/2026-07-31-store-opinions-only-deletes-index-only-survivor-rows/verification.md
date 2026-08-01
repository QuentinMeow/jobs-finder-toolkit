# Verification — 2026-07-31-store-opinions-only-deletes-index-only-survivor-rows

All commands run on branch `wip/33-store-p0-data-loss`, in a worktree with no
`config.yaml`; every store built under a throwaway temp root with `JOBHUNT_CONFIG`
pinned to a scratch config, so no build read or wrote the private tree.

## The defect, reproduced against the pre-fix builder

A store is built, then one entity's raw manifest *and* derived directory are both
removed — leaving its `index/postings.jsonl` row as the only record of it anywhere
in the store. `--opinions-only` then rewrites the index from `derived/` alone.

```
$ .venv/bin/python equiv_check.py          # pre-fix builder (HEAD), scratch harness
after raw+derived loss: ['ashby-ay-1', 'gh-111', 'gh-222', 'gh-333', 'gh-900'] | survivors: ['gh-222']
build_postings: mode=opinions-only, changed=0
after --opinions-only: ['ashby-ay-1', 'gh-111', 'gh-333', 'gh-900']
  DESTROYED: gh-222
build_postings: mode=incremental, fold=pending-only, ..., carried_from_index=0
build_postings: mode=rebuild, entities=5, suppressed=0, events=8, carried_from_index=0
  [stage5-after-opinions-only] incremental vs --rebuild: IDENTICAL
```

The last three lines are the reason this is a P0 rather than a cosmetic bug: after
the row is destroyed, the next incremental build reports `carried_from_index=0` and
still matches `--rebuild` byte for byte. Both paths agree perfectly on a store the
row has already been deleted from, so the equivalence contract cannot detect it and
`--rebuild` cannot repair it.

## Same harness, post-fix

```
$ .venv/bin/python equiv_check.py
after raw+derived loss: ['ashby-ay-1', 'gh-111', 'gh-222', 'gh-333', 'gh-900'] | survivors: ['gh-222']
build_postings: mode=opinions-only, changed=0, carried_from_index=1
after --opinions-only: ['ashby-ay-1', 'gh-111', 'gh-222', 'gh-333', 'gh-900']
  preserved verbatim at seq=2: gh-222
  [stage1] incremental vs --rebuild: IDENTICAL
  [stage2-annotated] incremental vs --rebuild: IDENTICAL
  [stage5-after-opinions-only] incremental vs --rebuild: IDENTICAL

RESULT: ALL CHECKS PASS
```

## The regression tests, before the fix

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -t skills/job-search/scripts/tests -k IndexPreservationTests -k EmptyStoreRebuildTests

FAIL: test_opinions_only_preserves_index_only_survivors
  AssertionError: Items in the second set but not the first:
  'gh-222'
  'gh-111'

FAIL: test_the_postings_index_has_exactly_one_writer
  AssertionError: 2 != 1 : index/postings.jsonl must have exactly ONE writer
  (_write_postings_index), which applies the durable floor; found 2 at line(s) [673, 1720]

Ran 10 tests in 6.236s
FAILED (failures=2, errors=3)
```

## The regression tests, after the fix

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -t skills/job-search/scripts/tests -k IndexPreservationTests -k EmptyStoreRebuildTests \
    -k OpinionsOnly -k SwapCrash

Ran 14 tests in 6.589s
OK
```

## Incremental == rebuild equivalence still holds

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -t skills/job-search/scripts/tests -v -k equals_rebuild -k agree_on_index_survivors \
    -k matches_rebuild -k staged

test_staged_incremental_equals_rebuild (DeterminismTests) ... ok
test_many_staged_builds_equal_one_rebuild (IncrementalFoldTests) ... ok
test_incremental_and_rebuild_agree_on_index_survivors (IndexPreservationTests) ... ok

Ran 3 tests in 3.597s
OK
```

## Full suites

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
    -t skills/job-search/scripts/tests
Ran 482 tests in 58.258s          # 477 before this branch; +5 new
OK

$ .venv/bin/python -m unittest discover automation/shared/tests
Ran 587 tests in 15.327s
OK
```

The tracked example store carries the builder's module stamp, so it was regenerated
(`automation/store/generate_fixture_store.py`) — the only diff is
`built_by: build_postings.py@5d2b88a9` → `@232b8019` in four `posting.yaml` files.
That regeneration is what `FixtureFreshnessTests` demands.

## Gates

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ .venv/bin/python automation/reconcile/reconcile.py --check
reconcile: OK (9 checks clean)

$ .venv/bin/python automation/store/validate_store.py examples/data --check-fixture-size
OK: store is valid.
fixture size OK: 13.5 KB / 100 KB soft threshold (default constant)
```

## Definition of done

- [x] `--opinions-only` preserves every `carried_from: index` row verbatim, at its
      original `seq` — asserted field-by-field in
      `test_opinions_only_preserves_index_only_survivors`.
- [x] A test builds a store, removes one entity's raw *and* derived, confirms the row
      survives an incremental build, then runs `--opinions-only` and asserts it still
      survives.
- [x] The `by-day` / `triage` zones are unaffected: the test snapshots both
      directories' bytes across the `--opinions-only` run and asserts equality.
- [x] The job-search suite passes.

The task also asked whether the fold cache needs touching. It does not.
`--opinions-only` rewrites `opinions` in `posting.yaml`, and the fold cache holds no
opinion — only the partition, the carried snapshot, the trailing-newline bit and the
duplicate-bucket triple, none of which this pass moves. Preserving survivors changes
only `index/postings.jsonl`, which the cache does not describe. The write-ahead
incomplete marker (already taken by this path) remains the correct answer to an
interrupted run.

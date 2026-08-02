# Verification — 2026-07-31-store-entity-that-changes-company-leaves-a-stale-derived-dir

Only commands actually run, with their real output.

## The bug, reproduced before any fix

A throwaway store; one aggregator row captured twice under two `companyName` values (the URL-derived
key does not move), then `raw/` removed to force carry-forward.

```
$ .venv/bin/python local/scratch/repro1.py
after build 1, partitions: ['zeta-corp']
after re-partition (incremental), partitions: ['alpha-labs', 'zeta-corp']
index rows: [('url-98453eb35413', 'Alpha Labs', 'Senior Backend Engineer')]
validate_store ok: True []
after carry-forward, partitions: ['alpha-labs', 'zeta-corp']
index row after carry-forward: [('url-98453eb35413', 'Zeta Corp', 'Backend Engineer',
                                 '2026-07-14T09:00:00Z')]
validate_store ok: True []
```

The last two lines are the finding the filed task did not have: the orphan does not merely sit
there, it WINS. `validate_store` calls the store ok in both states.

## The four new tests, run against the UNFIXED builder

`git stash push -- skills/job-search/scripts/build_postings.py`, then the four tests:

```
$ python -m unittest test_build_postings.IncrementalFoldTests.test_a_company_rename_moves_the_derived_dir_instead_of_forking_it \
    test_build_postings.IncrementalFoldTests.test_a_company_rename_moves_the_derived_dir_on_the_full_fold_too \
    test_build_postings.IncrementalFoldTests.test_a_key_at_two_partitions_refuses_the_fast_path \
    test_build_postings.CarryForwardTests.test_a_renamed_company_is_not_reinstated_by_carry_forward
FAIL: test_a_company_rename_moves_the_derived_dir_instead_of_forking_it
  AssertionError: Lists differ: ['alpha-labs', 'zeta-corp'] != ['alpha-labs']
FAIL: test_a_company_rename_moves_the_derived_dir_on_the_full_fold_too
  AssertionError: Lists differ: ['alpha-labs', 'zeta-corp'] != ['alpha-labs']
FAIL: test_a_key_at_two_partitions_refuses_the_fast_path
  AssertionError: 'fold=full' not found in '... fold=pending-only ...'
FAIL: test_a_renamed_company_is_not_reinstated_by_carry_forward
  AssertionError: Tuples differ: ('Zeta Corp', 'Backend Engineer')
                              != ('Alpha Labs', 'Senior Backend Engineer')
                              : carry-forward reinstated the pre-rename orphan
Ran 4 tests in 4.842s
FAILED (failures=4)
Exit: 1
```

The second test proves it is not a fast-path artifact: the same divergence appears with the fold
cache deleted, on the whole-raw-zone fold.

## With the fix

```
$ JOBHUNT_CONFIG=$PWD/config.example.yaml python -m unittest discover -s skills/job-search/scripts/tests
Ran 551 tests in 159.926s
OK
Exit: 0
```

(551 = the 547 that passed at `e91f6cb` plus these four.)

## Definition of done

- An entity whose partition moves leaves exactly one derived directory, at the new partition —
  `test_a_company_rename_moves_the_derived_dir_instead_of_forking_it` (fast path) and
  `..._on_the_full_fold_too` (fallback path), both asserting `partitions == ['alpha-labs']`.
- The removal is safe under "agents never delete owner data" — the only removal is
  `shutil.rmtree` over `<derived>/postings/<partition>/<key>`, guarded by a resolved-path check
  that raises `BuildError` on anything at a different depth or outside the zone. `raw/`,
  `annotations/` and `state/` are not touched by this change at all.
- A test captures the same aggregator row twice under two `companyName` values and asserts the
  incremental result is byte-identical to `--rebuild` — both rename tests end in
  `_assert_matches_rebuild()`, which rebuilds a clone of the pre-build generation in a store of
  its own and compares `derived/` and `index/` file-for-file.
- The suite passes (above).

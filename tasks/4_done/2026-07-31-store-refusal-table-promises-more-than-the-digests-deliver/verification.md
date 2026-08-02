# Verification — 2026-07-31-store-refusal-table-promises-more-than-the-digests-deliver

Only commands actually run, with their real output.

## The three gaps, reproduced against the UNFIXED builder

`git stash push -- skills/job-search/scripts/build_postings.py skills/job-search/scripts/postings_fold_state.py`,
then the three new tests:

```
$ python -m unittest \
    test_build_postings.IncrementalFoldTests.test_a_manifest_replaced_in_place_falls_back \
    test_build_postings.IncrementalFoldTests.test_a_deleted_event_log_falls_back \
    test_build_postings.IndexPreservationTests.test_a_row_deleted_from_the_committed_index_falls_back
FAIL: test_a_manifest_replaced_in_place_falls_back
  AssertionError: 'fold=full' not found in 'build_postings: mode=incremental,
    fold=pending-only, pending=1, entities=2, folded=1, ...'
FAIL: test_a_deleted_event_log_falls_back
  AssertionError: 'fold=full' not found in 'build_postings: mode=incremental,
    fold=pending-only, pending=1, entities=1, folded=1, ...'
FAIL: test_a_row_deleted_from_the_committed_index_falls_back
  AssertionError: 'fold=full' not found in 'build_postings: mode=incremental,
    fold=pending-only, pending=1, entities=2, folded=1, ...'
Ran 3 tests in 2.812s
FAILED (failures=3)
Exit: 1
```

Each test then asserts the surviving damage, so it is not only a missing refusal:

| Gap | What the unfixed build leaves |
|---|---|
| manifest replaced in place (same `fetch_id`, new `payload.blob`) | index keys `{gh-111, gh-444}`; a `--rebuild` of the same raw has `{gh-111, gh-333, gh-444}` |
| `events.jsonl` deleted under a surviving `posting.yaml` | events `['first_seen','seen','changed']` -> `['seen','changed']`; `by-day/` down to the newest day alone |
| a row hand-deleted from `index/postings.jsonl` | index `['gh-111']`; `--rebuild` gives `['gh-111','gh-222']` |

## With the fix

```
$ python -m unittest <the same three tests>
Ran 3 tests in 3.814s
OK
Exit: 0

$ JOBHUNT_CONFIG=$PWD/config.example.yaml python -m unittest discover -s skills/job-search/scripts/tests
Ran 557 tests in 151.009s
OK
Exit: 0
```

## The cache-schema bump and the tracked fixture

`automation/shared/tests` failed after the builder edit and named its own repair:

```
$ python -m unittest discover automation/shared/tests
FAIL: test_tracked_fixture_matches_a_fresh_generator_run
  AssertionError: ['jobs/derived/postings/examplecorp/gh-1234567/posting.yaml',
                   'jobs/derived/postings/examplecorp/gh-7654321/posting.yaml',
                   'jobs/derived/postings/ghostworks/ck-53ef9a5b59d7/posting.yaml',
                   'jobs/derived/postings/remoteworks/url-b839730d7cbd/posting.yaml'] != []
  : tracked example-store files are stale against the builder that writes them —
    re-run automation/store/generate_fixture_store.py and commit the result
Ran 621 tests in 22.049s
FAILED (failures=1)
Exit: 1
```

Confirmed to be a pure builder-stamp effect, not a content change — the stale value is exactly
the pre-change builder's hash:

```
$ python -c "sha256(<e91f6cb build_postings.py>)[:8]"
370e547e          # == the stamp in the tracked fixture
$ python -c "sha256(<current build_postings.py>)[:8]"
6cd1dbd7          # == the stamp after regeneration
```

```
$ python automation/store/generate_fixture_store.py
fixture store generated at .../examples/data
Exit: 0
$ git diff --stat -- examples/data
4 files changed, 4 insertions(+), 4 deletions(-)   # one `built_by:` line each

$ python -m unittest discover automation/shared/tests
Ran 621 tests in 50.073s
OK
Exit: 0
```

## Definition of done

- Each of the three gaps is closed in code, with the reason stated (in the function docstrings,
  the commit body, and the reworded rows of
  `docs/designs/raw-data-layer/05-incremental-build.md`).
- The tightened digest is called out as a one-time full fold for existing stores — in the commit
  body, in the `_store_state` docstring, and beside `CACHE_SCHEMA = 2` in
  `skills/job-search/scripts/postings_fold_state.py`.
- One test per gap (above), each failing against the previous code.
- The suite passes (557/557 above).

## Repository gates, at the branch tip

```
$ python -m unittest discover -s skills/job-search/scripts/tests   Exit: 0   (557 tests)
$ python -m unittest discover automation/shared/tests              Exit: 0   (621 tests)
$ skills/job-search/scripts/validate_filter_variants.py --check    Exit: 0
$ automation/reconcile/reconcile.py --check                        Exit: 0
$ automation/publish/check_public.py --staged --allow-unarmed      Exit: 0
$ automation/gardener/verify_links.py --require-roots --no-overlay Exit: 0
$ automation/metrics/instruction_budget.py --strict                Exit: 0
$ automation/vendoring/sync_vendored.py --check                    Exit: 0
$ automation/publish/review_gate.py --verify-all                   Exit: 0
```

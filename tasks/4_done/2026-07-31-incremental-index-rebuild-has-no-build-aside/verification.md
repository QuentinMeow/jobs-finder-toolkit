# Verification — 2026-07-31-incremental-index-rebuild-has-no-build-aside

Only commands actually run, with their real output.

## The bug, and its real (narrower) extent

`IndexRegenCrashTests` builds a store holding two postings (so `by-day/` has rows) and one
structurally-foreign scrape row (so `triage/` has one), then injects
`OSError(28, "No space left on device")` on the `postings.jsonl` write — which in
`_regen_index_zone` lands immediately after the destructive step. Run against the UNFIXED
builder (`git stash push -- skills/job-search/scripts/build_postings.py`):

```
$ python -m unittest test_build_postings.IndexRegenCrashTests
FAIL: test_a_failed_incremental_index_write_leaves_by_day_and_triage
  AssertionError: {'by-day': 'MISSING', 'postings.jsonl': True, 'triage': 'MISSING'}
              != {'by-day': ['2026-07-14.jsonl'], 'postings.jsonl': True,
                  'triage': ['suppressed-2026-07.jsonl']}
Ran 3 tests in 6.549s
FAILED (failures=1)
Exit: 1
```

`'postings.jsonl': True` in the failing state is the correction to the filed report: the durable
floor survives, and always did. Only `by-day/` and `triage/` are lost.

Two of the three tests pass before the fix, on purpose, and are labelled as such:

- `test_rebuild_already_survives_the_same_failure` is the CONTROL — it runs the identical
  injected failure through `--rebuild` and shows the zone intact. It documents the behaviour the
  incremental path is being brought level with; it is not evidence of the defect.
- `test_a_bucket_that_empties_still_loses_its_file` is a non-regression guard on the new code
  (write-first must not become never-prune). It passed before the fix trivially, because the old
  code `rmtree`d everything.

## With the fix

```
$ python -m unittest test_build_postings.IndexRegenCrashTests
Ran 3 tests in 5.303s
OK
Exit: 0

$ JOBHUNT_CONFIG=$PWD/config.example.yaml python -m unittest discover -s skills/job-search/scripts/tests
Ran 554 tests in 144.452s
OK
Exit: 0
```

## Definition of done

- `_regen_index_zone` no longer deletes any part of the live index zone before its replacement
  is written. It snapshots the existing `by-day/`, `triage/` and stale top-level `*.jsonl`
  files, calls the two writers (which now report the paths they wrote), and unlinks only
  `before - written`.
  - Deviation from the filed shape, deliberately: the task suggested building the whole zone
    into `index.building` and reusing `_swap_dir`, and also asked that a full build-aside be
    checked against the incremental path's whole point before committing to it. Write-then-prune
    achieves the same crash property (nothing is removed until its replacement is on disk) for
    one extra listing of two directories, copies no survivor rows a second time, and keeps
    `.building` / `.old` directories out of `index/`.
- A test injects a failure inside the index write and asserts the pre-existing state survives,
  and it fails against the current code — `test_a_failed_incremental_index_write_leaves_by_day_and_triage`,
  output above. The assertion is over the whole zone including `postings.jsonl` (which was
  already safe, and is asserted to stay safe).
- `test_build_postings.py` still passes, including `IndexPreservationTests` and the
  incremental-equals-rebuild byte-identity tests (554/554 above; `_assert_matches_rebuild` runs
  inside `test_a_bucket_that_empties_still_loses_its_file` as well).
